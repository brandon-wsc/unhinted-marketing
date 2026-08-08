# ADR 0009 — Unified intent + research gate; Tavily ingest alongside PG

- **Status:** Accepted
- **Date:** 2026-08-08
- **Supersedes:** —

## Context

Session `chat` is under-grounded (history only; no tools). Free web browse or a parallel knowledge store would violate PostgreSQL-only knowledge and blur Confirm ≠ LLM. Tavily is a viable **ingest source** if results land in `raw_news_events` like Google Trends.

We also lack a clear policy for: when to search, how to turn messy user text into a search query, whether PG hits should skip search, and how `route_intent` relates to a finer “need facts” classifier. External LLM APIs do not expose internal confidence scores, so `need_search` cannot rely on model introspection.

## Decision

1. **Single classifier node (extend `route_intent`)** — One structured LLM call outputs both:
   - `graph_intent`: `chat` | `start` | `revise` | `confirm_intent` (unchanged graph routing)
   - `research`: `{ need_facts, ambiguous, ask_clarify, … }` (chat/research side channel)
   Do **not** keep a separate `intent_classifier` node that re-decides graph routing.

2. **`fast_rule_checker` before the classifier (optional short-circuit)** — Deterministic rules may skip research / Tavily (e.g. pure chitchat, product-howto). Fail → proceed to `chat` (or agent path from `graph_intent`) without query generation. Pass → still run the unified classifier. Rules do not replace ambiguity handling.

3. **`query_generator` only after gates pass** — When `need_facts` and not `ask_clarify` / not `ambiguous`, a node (or step) emits a **short** `search_query` (+ optional `time_range` / `topic`). Never send raw multi-turn chat verbatim to Tavily. Simple already-search-like utterances may skip an extra LLM and only normalize.

4. **PG ∪ Tavily (both)** — When research runs, **always** query existing PostgreSQL signals **and** call Tavily (or equivalent), then **upsert** Tavily hits into `raw_news_events` with provenance (`source=tavily`, url, excerpt, `signal_id`). Do **not** skip Tavily because PG already has rows — corpora differ. Token/credit savings are not a reason to skip either source.

5. **Understand ≠ search; act ≠ search success** — Clarifying what the user wants (`graph_intent`, ambiguity) is NLU / clarify dialogue, **not** Tavily. Taking action (`start` / revise agent path) is gated on clear intent (and clarify when `ambiguous`), **not** on Tavily or PG search success. Research may run in parallel or after routing to enrich context; failure to search must not block `start`.

6. **LLM zone still read-only on tools** — Session nodes consume PG (via repos / `query_market_trends` shape). Tavily is an **ingest adapter** (worker or session-triggered upsert), not a free-browse tool that answers without persistence. Publish remains HTTP Confirm only ([ADR 0003](./0003-confirm-without-llm.md)).

## Consequences

- Extend `IntentRoute` (or successor schema) + `ROUTE_INTENT` prompt; add `fast_rule_checker`, `query_generator`, Tavily ingest adapter; wire chat (and optionally `trend_searcher`) to merged PG+Tavily signal sets.
- Heuristic `_heuristic_intent` remains offline / parse-fail fallback only; research flags need a deterministic fallback policy (e.g. `need_facts=false` when no LLM).
- Env: `TAVILY_API_KEY` (and related); STATUS/ROADMAP list Tavily as an ingest source alongside Trends / future Meta.
- Ambiguous entities (e.g. “usagi”) → `ask_clarify` / chat clarification **before** query generation or acting on a guessed sense.
- Implementation is accepted as product contract; shipping code may land in follow-up PRs without changing this ADR unless superseded.
