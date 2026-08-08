# ADR 0007 — Admin Trace viewer (node-steps + session)

- **Status:** Accepted
- **Date:** 2026-08-03
- **Supersedes:** Deferred “persist full node-step I/O” / Trace viewer UI notes in [ADR 0005](./0005-platform-levels-and-llm-records.md); closes ROADMAP “Trace viewer: session messages + revision timeline + signal grounding links” as an **admin** tool
- **Related:** [ADR 0006](./0006-api-path-prefix-and-spa-proxy.md) (API under `/api`; SPA `/admin` no longer shares a vite proxy prefix); [ADR 0009](./0009-research-gate-and-tavily-ingest.md) (Research tab)

## Context

LLM call records (ADR 0005) show prompts/responses but not the full graph path: which non-LLM nodes ran, mode/intent transitions, or draft revisions grounded in signals. `node_trace_recording()` existed only for tests. ROADMAP listed a Trace viewer; product users do not need it — platform admins debugging fine-tuning do.

## Decision

1. **Persist node steps in production** — Each `_invoke_graph` turn gets a `turn_id`. `turn_trace(...)` collects `NodeStepRecord`s (already emitted by `record_node_step` / `@agent_progress`) and flushes them to `session_node_steps` (background INSERT, `NODE_TRACE_ENABLED`). `llm_call_records.turn_id` joins LLM rows to the same turn.
2. **Admin APIs** (gated by `require_platform_level(ADMIN)`, not tenant ownership):
   - `GET /admin/node-steps` + `/{id}` (sibling LLM calls by `turn_id`+`node`)
   - `GET /admin/sessions/{id}/trace` — messages, draft revisions, resolved signals, turns (steps + LLM calls)
   - `GET /admin/sessions/{id}/research` — ADR 0009 per-turn gate + queries + Tavily∪PG hits (aggregated from research node-step outputs)
3. **Admin UI** at SPA `/admin` with tabs: LLM calls | Node steps | Research | Session Trace; deep-link via `?tab=&turn=&session=`. LLM detail / Session Trace can jump to Research for the same `session_id`.
4. **Not** an end-user debugger. Retention/purge remains deferred.

## Consequences

- Every graph turn writes N node-step rows (capped JSON output) in addition to LLM records.
- Tests keep `node_trace_enabled=False` by default (autouse fixture); unit tests still use in-memory `node_trace_recording()`.
- ROADMAP Trace viewer checkbox is satisfied via admin Session Trace tab.
