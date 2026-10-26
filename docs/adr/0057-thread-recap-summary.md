# ADR 0057 — Rolling thread recap for long sessions

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

LLM context per turn is windowed: `route_intent`, `query_generator`, and the fallback query hint read `_recent_thread` (last 6 messages, 400 chars each); the `chat` node reads `messages[-8:]`. Everything older is invisible to those nodes, even though the full transcript is loaded into graph state every turn.

The durable working set — brief, draft, image_plan, ranked signals, persona, products — already lives in structured `session.state`, and that stickiness across turns is intentional. What the windows cannot carry is *conversational* memory: a user who keeps one session for many turns and references a topic from 5+ exchanges ago ("頭先嗰個 topic", "繼續講嗰個") gets a query rewrite or intent classification that cannot see the referent. Users also state preferences or reject options early that never land in structured state.

A free-text rolling summary is the standard fix, but it introduces two risks worth bounding: a summary is LLM-authored memory that can go stale or hallucinate old "facts" (the user may have changed their mind since), and it adds an LLM call to every turn unless the trigger is deterministic.

## Decision

1. **`thread_recap` is a plain graph node** between `fast_rule_checker` and `route_intent`, not a service-layer side effect — it gets node-step tracing, LLM-call recording, and mock coverage like every other LLM node.

2. **Deterministic trigger, incremental fold.** The node keeps the last **16** messages raw (`RECAP_RAW_TAIL`) and folds the older prefix into `thread_summary`. It calls the LLM only when at least **8** new messages (`RECAP_MIN_NEW`) have aged past the window since `summary_upto` — the count of leading messages already folded. Input is `{prior_summary, new_messages}`: the prior summary plus only the newly-aged slice, never the whole transcript. Short sessions never pay for the call.

3. **`thread_summary` + `summary_upto` live in session state** like any other sticky field: persisted via `_graph_values` / `_persist_after_invoke`, checkpointed with graph values. Discard/Stop restores `pre_state`, so the pair rolls back together — the summary can never describe a future that was discarded, only a slightly older past.

4. **Summary is stale-labeled background, not ground truth.** Consumers get it as a separate `thread_summary` payload field, never merged into `recent_thread`/`history`. The consumer prompts (`ROUTE_INTENT`, `QUERY_GENERATOR`, `CHAT`) state it may be stale and must not override the current message or live structured state.

5. **First consumers: `route_intent`, `query_generator`, `chat`** — the nodes whose job is referent resolution and conversational coherence. `executor_post`, `edit_copy`, `reviewer`, and `brainstormer` do NOT receive it: their working set is the structured state, and an LLM-authored recap must not become a grounding/craft surface.

6. **Recap degrades, never blocks.** Missing credentials or a provider error inside `thread_recap` returns `{}` — the turn proceeds with a stale (or absent) summary and retries next turn.

7. **Checkpoint messages are unchanged.** This ADR bounds *what the LLM sees*; the full transcript still flows through state/checkpoint for resume and discard mechanics.

## Consequences

- Cost: zero for sessions under ~24 messages; afterwards one CHEAP-tier call per ~8 new aged messages (~4 exchanges). Node-step rows record the node's I/O for prompt tuning.
- Correctness bound: worst case after the change is the same as today (summary absent) plus a possibly-stale hint that consumers are told to distrust — never a regression in grounding, since grounded consumers never see it.
- The summary is a heuristic memory; it is not surfaced to the user and must not be treated as a citation source.
- Resume paths (`ainvoke(None)`) do not re-run `thread_recap`; the summary lags at most one parked turn.
