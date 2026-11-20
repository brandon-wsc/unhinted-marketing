# ADR 0062 — Session main agent: collapse the cognition pipeline; supersedes nothing yet

- **Status:** Accepted (draft open questions resolved 2026-11-21 — see §Resolved questions)
- **Date:** 2026-11-21
- **Related:** [ADR 0061](./0061-create-agent-inner-loop.md) (inner loop is `create_agent`); [ADR 0009](./0009-research-gate-and-tavily-ingest.md) (research gate); [ADR 0028](./0028-angle-pick-before-draft.md) (angle park); [ADR 0036](./0036-image-direction-new-script.md) (image park + direction change); [ADR 0016](./0016-queue-send-while-turn-in-flight.md) + [ADR 0035](./0035-queue-then-interrupt.md) (queue/interrupt semantics); [ADR 0003](./0003-confirm-without-llm.md) (Confirm stays HTTP); [ADR 0004](./0004-stop-discard-and-image-resume.md) (Stop → abort, no blind resume); [ADR 0047](./0047-session-file-attachments.md) (`read_attachment`); [ADR 0057](./0057-thread-recap-summary.md) (thread recap)

## Context

The session graph encodes a fixed cognition pipeline as vertices and conditional edges:

```text
route_intent ─┬─ query_generator → research_ingest ─┐
              ├─ load_context → trend_searcher → product_matcher
              │     → brainstormer → [angle_gate ⏸] → executor_post
              │     → grounding_check → reviewer ⇄ edit_copy (cap)
              │     → executor_image_plan → [executor_image_gen ⏸]
              │     → persist_preview
              ├─ edit_copy / ack_confirm / chat
              └─ (ADR 0016 queue + ADR 0035 interrupt wrap all of it)
```

This shape made sense when model reliability needed scaffolding. The costs it now charges:

- **The graph is a workflow builder.** `route_intent → research → trend → match → brainstorm → draft` is a pre-computed plan a capable model can orchestrate itself. LangChain's own guidance (post-`langgraph-supervisor` deprecation) is: sub-agents as `@tool`s on a main agent; graphs encode guarantees, not cognition. Every flow variant costs new nodes + edges + route functions instead of a prompt/tool change.
- **Routing is paid twice.** `route_intent` is a classifier (an LLM call) whose output could be the main agent's first tool-selection decision. `research_ingest`'s conditional fan-out re-asks "what next" deterministically on top of it.
- **Node-chained context passing is brittle.** `load_context` → `trend_searcher` → `product_matcher` → `brainstormer` → `executor_post` is five hops of SessionState fields being shaped for the next prompt. A sub-agent invocation boundary (deps in, typed result out) is a cleaner seam for the same data.

What must not move (restated — this ADR changes *who decides*, not *what is guaranteed*):

- Confirm / `publish_social_post` / catalog upsert stay traditional HTTP ([ADR 0003](./0003-confirm-without-llm.md), [ADR 0011](./0011-knowledge-commit-without-llm.md)).
- Both parks stay product-owned interrupts with HTTP resume: angle pick ([ADR 0028](./0028-angle-pick-before-draft.md)) and image gen ([ADR 0036](./0036-image-direction-new-script.md)). "Where the turn may pause and how it resumes" stays a property of code, not model judgment.
- Stop → abort in-flight; parked turns resume only via their verbs; queued sends and empty-Enter interrupt semantics unchanged ([ADR 0004](./0004-stop-discard-and-image-resume.md), [0016](./0016-queue-send-while-turn-in-flight.md), [0035](./0035-queue-then-interrupt.md)).
- `persist_preview` writes the canonical draft deterministically ([ADR 0001](./0001-preview-canonical-draft.md), [0008](./0008-preview-images-append-only.md)); `grounding_check`'s claim-vs-signal validation must run on every draft, not when the model feels like it.
- PostgreSQL-only knowledge; REST SSOT; CI mocks the LLM; the eval seams (`run_executor_post_agent`, `run_query_generator_agent`, `N.grounding_check`, etc.) stay callable with the same signatures so `tests/eval` keeps grading — the refreshed baseline (`reports/eval/baseline.json`, PR #192) is the pre-refactor ruler.

## Decision

### 1. One `session_agent` vertex owns the cognition; the outer graph owns guarantees

Replace the `route_intent … executor_post/edit_copy` pipeline with a single `create_agent` vertex — the main session agent — holding the turn's tools. The outer `StateGraph` keeps only what is not cognition:

```text
fast_rule_checker → thread_recap → session_agent ─┬─→ grounding_check → review_gate
                                                   │      ⇄ (agent re-enter, capped)
                                                   ├─→ persist_preview → END
                                                   ├─→ [park: angle pick ⏸ / image gen ⏸]
                                                   └─→ END (chat reply)
```

Disposition of current nodes:

| Current node | Becomes | Why |
|---|---|---|
| `fast_rule_checker` | outer node (unchanged) | deterministic kill-switch before any LLM spend |
| `thread_recap` | outer node or agent middleware | conditional LLM recap; either is honest — pick at implementation |
| `route_intent` | gone — the main agent's own tool selection | classification-by-LLM was a second price for routing the model can do inline |
| `query_generator` + `research_ingest` | `research` tool → sub-agent (`create_agent` + `ToolStrategy(QueryGenOut)`); ingest stays a deterministic write inside the tool | context isolation keeps raw hits out of the main transcript; ingest never becomes an LLM decision |
| `load_context` | deterministic context-builder inside the draft tool's entry | a `SELECT`, not a judgment |
| `trend_searcher` | folded into the draft sub-agent's context (its prompt work) | it re-reads signals already fetched; the sub-agent owns "which trends matter" |
| `product_matcher` | deterministic catalog query — either a tool or part of draft context assembly | no LLM today; stays non-LLM |
| `brainstormer` | `propose_angles` tool → sub-agent returning typed angles + recommended pick | cognition, kept typed for the angle-park payload |
| `angle_gate` | **outer vertex, unchanged** — `interrupt()` inside a tool is unavailable: the leaf `create_agent` carries no checkpointer (ADR 0061 §1), so a dynamic interrupt cannot persist a resume point. All ADR 0028/0004/0016/0035 park semantics stay bound to `interrupt_before` | ADR 0028 semantics do not move |
| `executor_post` | `draft_post` tool → sub-agent (`DraftOut`) — keeps `run_executor_post_agent` signature for eval | cognition |
| `grounding_check` | deterministic post-check — runs on every draft via outer edge or middleware, never a tool the model may skip | product post-condition |
| `reviewer` + `review_exhausted` | **outer LLM node + outer cap, unchanged** — review pass/fail and `_reviewer_fail_bump` are product policy; the agent re-enters for the `edit_copy` leg only | retry budget is not cognition |
| `edit_copy` (revise + fix paths) | `revise_draft` tool → sub-agent (`EditOut`) — keeps `run_edit_copy_agent` signature | cognition |
| `executor_image_plan` | `plan_image` tool on the agent — script+plan is cognition, and "does this post want an image" becomes a model decision instead of a `route_after_reviewer` flag read | cognition |
| `executor_image_gen` + image park | **outer node + park, unchanged** — gen is a deterministic media-adapter call behind a durable human gate (same checkpointer argument as `angle_gate`); `hold_locked_plan` stays an outer path | ADR 0036 direction-change rules do not move |
| `persist_preview` | outer node (unchanged) | canonical-draft write is a post-condition |
| `chat` | the main agent's default reply path (no tool) | — |
| `ack_confirm` | intercepted in the `fast_rule_checker` layer (pre-agent, deterministic) — confirm-adjacent wording never reaches model discretion | ADR 0003 |

### 2. The agent never owns the state machine

- `SessionState`, the Postgres checkpointer, `turn_registry`, and the park/resume verbs stay exactly where they are. The `session_agent` vertex is a bigger version of today's inner `create_agent` leaves — state is per-call scratch; parks are expressed as interrupts the outer graph observes, matching the ADR 0061 leaf-graph stance.
- Parks can *only* be outer: a durable interrupt needs a checkpointer to hold its resume point, and the leaf `create_agent` carries none by design (ADR 0061 §1). `interrupt()` inside a tool is therefore not an available implementation for either park — both stay `interrupt_before` vertices.
- Per-turn budgets keep their shape: `attachment_reads` cap, Tavily query cap, review-attempt cap — all enforced in code the model cannot route around.
- Model tiers: the main agent uses the `chat`/`executor_post` tier; sub-agents keep their own `NODE_MODEL_TIERS` entries so cost routing survives the collapse.

### 3. Eval seams are a hard requirement

Every `tests/eval` case today is node-keyed (`_run_case` calls `N.route_intent`, `run_executor_post_agent`, `N.grounding_check`, …). The refactor is only mergeable if:

- the `run_*_agent` functions keep existing with the same signatures even when no longer a graph vertex (they become the sub-agent entry points), and
- `eval_diff` against the PR #192 baseline stays meaningful — same case set, same graders, same model.

New gap admitted: no session-level eval exists today (message in → which tool fired → which park hit). A small set of tool-selection cases ships with the refactor — otherwise `eval_diff` can be all-green while routing walked off.

## Resolved questions (from the draft discussion)

1. **Angle park mechanics → outer vertex.** `interrupt()` inside a sub-agent tool is not available: the leaf `create_agent` is deliberately checkpointer-free (ADR 0061 §1), and a dynamic interrupt has nowhere to persist its resume point — a process restart would lose the park. `angle_gate` stays a vertex under `interrupt_before`; the draft path exits through it exactly as today. The same argument applies to the image park.
2. **Reviewer placement → outer.** The review cap and `_reviewer_fail_bump` are the clearest "product policy, not cognition" left in the pipeline; making the loop an agent tool would only blur the budget. `reviewer`/`review_exhausted` keep their edges; the agent owns the `edit_copy` revision leg they route back into.
3. **Image path → plan in, gen out.** `executor_image_plan` (script+plan writing) folds into the agent as `plan_image`, and whether a post wants an image at all becomes a model decision. `executor_image_gen` stays outer: it is a deterministic media-adapter call gated by a durable human park, which needs the outer checkpointer anyway. Splitting at cognition/not-cognition mirrors `persist_preview`.
4. **`ack_confirm` → pre-agent intercept.** Confirm-adjacent wording ("搞掂未？") is answered in the `fast_rule_checker` layer deterministically and never reaches the model — the strongest reading of ADR 0003.
5. **Queue/interrupt plumbing → pre-implementation mapping pass.** ADR 0016/0035 semantics bind to superstep boundaries; collapsing ~10 vertices into ~3 changes where a Stop lands. The mapping below is the result of that pass — kept here as implementation notes.

## Implementation notes — semantic re-binding map

Park/resume/stop survives unchanged because the mechanics key off *vertex names under `interrupt_before`*, and both park vertices stay: `service.py` reads `snapshot.next[0]` to set `awaiting_image_ok`/`awaiting_angle_pick` and to pick the resume verb (`_PARK_NOT_PARKED`); `turn_registry` holds in-flight turns and re-parks via `_repark_graph_at_interrupt`. What actually re-binds:

| Semantic | Bound today at | Re-binds at |
|---|---|---|
| Angle park (0028) + `choose_angle` resume | `angle_gate` vertex, `interrupt_before`; `snapshot.next[0]` | unchanged |
| Image park (0004/0036) + `resume_image`, `hold_locked_plan` | `executor_image_gen` vertex, `interrupt_before` | unchanged |
| Stop → abort upstream (0004) | `turn_registry` task cancel → `aclose_stream` in inner agent | unchanged — cancel propagates through `session_agent.astream` identically |
| Queue while in-flight / empty-Enter interrupt (0016/0035) | `turn_registry` busy check + `TurnEntry.mode` at turn entry | unchanged — entry/exit shape identical |
| Image-park explicit Send → new script (0036) | `revise_while_image_parked` writes state, graph re-parks | revise leg becomes the `plan_image`/edit tools; the re-park write is unchanged |
| Confirm/publish (0003), catalog upsert (0011) | HTTP only, never graph | unchanged; plus new pre-agent `ack_confirm` intercept |
| Canonical draft persist (0001/0008) | `persist_preview` vertex | unchanged |
| `grounding_check` on every draft | fixed edge `executor_post → grounding_check` | outer edge or middleware after any draft-producing agent return — must not depend on which tool fired |
| Thread recap (0057) | vertex before `route_intent` | unchanged position (pre-agent) |
| LLM call records (0005) | `_with_llm_record_context` per vertex name | one context on `session_agent` + per-sub-agent caller tags inside tools, or trace loses per-step attribution |
| `read_attachment` budget (0047), Tavily caps (0009) | deps closed over per call | unchanged — tool closures still per-turn |
| `agent.progress` SSE | `publish_agent_progress(state, node)` per vertex | fewer vertices = fewer progress beats; emit per-tool-call progress or the UX regresses |
| Interrupt salvage | `prior_message_count` diff cursor keeps committed node output | fewer vertices = fewer commit points; mid-agent cancel already keeps streamed partial text (0061 §2) — verify no silent loss vs. today |

Two reads to audit before deleting anything: whatever still keys on `state["intent"]` (the field `route_intent` wrote — UI flags, service branches) and every `route_after_*` state's field consumption, since the agent's tool choice replaces them without writing those fields.

## Consequences

- SessionState shrinks: fields that exist only to hand data node-to-node (`ranked_signals`, product payloads, angle scratch) collapse into tool-call inputs/outputs. Fields that are product state (parks, preview, draft, queue) stay.
- Prompt surface concentrates: five thin node prompts → one main prompt + per-sub-agent prompts. Voice rules (`VOICE.md`, `roast_level`) move into the draft sub-agent prompt — the eval voice judge keeps them honest.
- `scripts/eval_agent.py`'s `_run_case` gains session-level drivers; node cases keep working through the preserved seams.
- Failure-mode shift: deterministic pipeline bugs (wrong edge) become agent bugs (wrong tool, skipped tool). Mitigations are the deterministic post-checks above + the new session-level eval cases — not more edges.
- The `Dify-feel` test: adding a flow variant should mean a prompt/tool change, not a graph migration. That is the acceptance bar for this refactor.

## Rejected alternatives

- **Keep the pipeline, just use `create_agent` inside every node (status quo post-0061).** Pays the routing tax twice and keeps workflow-builder cost on every variant. The inner-loop migration already proved the model can drive a tool loop; this ADR extends the same bet one level out.
- **`langgraph-supervisor` / worker-as-subgraph hierarchy.** Deprecated upstream; tool-wrapped sub-agents give the same topology with fewer moving parts.
- **Full handoffs / state-machine pattern (single agent re-configured per `current_step`).** Tempting for user-facing state, but it makes step transitions tool decisions — exactly what the parks must not be.
- **Single mega-agent, no sub-agents.** Loses context isolation for research hits, tier routing per cognition type, and the per-node mock seams CI/eval depend on.
