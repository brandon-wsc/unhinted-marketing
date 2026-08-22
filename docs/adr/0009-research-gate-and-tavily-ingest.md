# ADR 0009 — Unified intent + research gate; Tavily ingest alongside PG

- **Status:** Accepted
- **Date:** 2026-08-08
- **Supersedes:** —
- **Related:** [ADR 0007](./0007-admin-trace-viewer.md) (admin Research tab aggregates gate + ingest)

## Context

Session `chat` is under-grounded (history only; no tools). Free web browse or a parallel knowledge store would violate PostgreSQL-only knowledge and blur Confirm ≠ LLM. Tavily is a viable **ingest source** if results land in `raw_news_events` like Google Trends.

We also lack a clear policy for: when to search, how to turn messy user text into a search query, whether PG hits should skip search, and how `route_intent` relates to a finer “need facts” classifier. External LLM APIs do not expose internal confidence scores, so `need_search` cannot rely on model introspection.

## Decision

1. **Single classifier node (extend `route_intent`)** — One structured LLM call outputs both:
   - `graph_intent`: `chat` | `start` | `revise` | `confirm_intent` (unchanged graph routing)
   - `research`: `{ need_facts, ambiguous, ask_clarify, entity_surface, … }` (chat/research side channel)
   Do **not** keep a separate `intent_classifier` node that re-decides graph routing.

2. **`fast_rule_checker` before the classifier** — Prefer semantic-router + FastEmbed (multilingual MiniLM; fail closed to regex if disabled/unavailable). Only `need_search` → `research_rule_pass=true`. Fail → proceed from `graph_intent` without `query_generator` / Tavily. Pass → still run the unified classifier. Rules do not replace ambiguity handling for **drafting**.

3. **`query_generator` after research gates** — When `research_rule_pass` and `need_facts`, emit **1–3 atomic `search_queries`** (+ optional `time_range` / `topic`). Never send raw multi-turn chat or spoken Cantonese clauses verbatim to Tavily.
   - Cheap path: only when the *user* line is already keyword-like (`normalize_search_query`).
   - Colloquial user text always goes through LLM; `entity_surface` is a hint only.
   - **Mixed Latin+CJK** pastes (e.g. `usagi 兔糧`) are **not** ready Tavily queries — reject in normalize; LLM must expand CJK product nouns to English; deterministic gloss fallback if LLM unavailable (`兔糧` → `rabbit food`).
   - **Ambiguity does not block this node** — searchable phrases still generate queries best-effort.

4. **PG ∪ Tavily (both)** — When research runs, **always** query existing PostgreSQL signals **and** call Tavily for each atomic query, then **upsert** hits into `raw_news_events` with provenance (`source=tavily`, url, excerpt, `signal_id`). Do **not** skip Tavily because PG already has rows — corpora differ.

5. **Understand ≠ search; act ≠ search success** — Clarifying what the user wants for **drafting** (`graph_intent` start/revise) may use `ask_clarify` when senses conflict. **Searchable user phrases must still run research** even if `ambiguous` is true — do not replace Tavily with a clarify quiz. Taking action (`start` / revise) is gated on clear intent when ambiguous; failure to search must not block `start` when intent is clear.

6. **LLM zone still read-only on tools** — Session nodes consume PG (via repos). Tavily is an **ingest adapter** (`internal/perception/tavily.py`), not a free-browse tool that answers without persistence. Publish remains HTTP Confirm only ([ADR 0003](./0003-confirm-without-llm.md)).

7. **Admin Research surface** — Ops inspect gate + ingest via `GET /api/admin/sessions/{id}/research` and `/admin?tab=research` ([ADR 0007](./0007-admin-trace-viewer.md)).

8. **Search ran ≠ signals trusted (soft-fail + mark)** — Graph still continues after query-generator parse miss or Tavily empty/error (gloss + PG∪Tavily still run). Downstream nodes must **not** treat leftover PG / gloss hits as this turn’s facts. Side channel on `research`:
   - `query_source`: `llm` | `normalize` | `fallback` (how queries were produced; ops/admin)
   - `signals_trusted`: bool (the only flag consumers read) — `false` when `query_source=fallback` **or** this turn produced no Tavily items
   Chat/draft/reviewer prompts get `signals_trusted` only — never JSON-parse / infra wording. Reviewer parse miss is **fail-closed** (`reviewer_passed=false`) with generic craft/grounding feedback.

## Consequences

- Extend `IntentRoute` + `ROUTE_INTENT` / `QUERY_GENERATOR` prompts; add `fast_rule_checker`, `query_generator`, `research_ingest`, Tavily adapter; wire chat (and optionally `trend_searcher`) to merged PG+Tavily signal sets.
- Heuristic `_heuristic_intent` remains offline / parse-fail fallback only; research flags default `need_facts=false` when no LLM.
- `research.query_source` / `research.signals_trusted` mark search quality for downstream nodes; reviewer parse miss is fail-closed.
- Env: `TAVILY_API_KEY`, `SEMANTIC_ROUTER_*`; STATUS/ROADMAP list Tavily as an ingest source alongside Trends / future Meta.
- Implementation ships on `feat/session-research-tavily`; further prompt/utterance tuning does not require a superseding ADR unless the gate contract changes.
