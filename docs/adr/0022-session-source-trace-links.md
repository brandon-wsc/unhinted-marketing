# ADR 0022 — Session source-trace links (user-visible `source_signal_ids`)

- **Status:** Accepted
- **Date:** 2026-08-31
- **Related:** [ADR 0001](./0001-preview-canonical-draft.md) (canonical preview payload); [ADR 0002](./0002-rest-source-of-truth-sse-enhancement.md) (REST hydrate + SSE merge); [ADR 0007](./0007-admin-trace-viewer.md) (ops Trace stays separate)

## Context

The session graph already grounds factual claims on PostgreSQL `raw_news_events` via `source_signal_ids` (draft rows, `sessions.state`, SSE `signals.updated` as ids only). Humans could not follow a preview or chat claim back to title / excerpt / URL without reading agent source or the admin Session Trace tab. MVP Definition of Done item 7 was open on the UI side.

## Decision

1. **No second knowledge store** — resolve citations with `get_signals_by_ids` against PostgreSQL only.
2. **REST SSOT** — `GET /api/sessions/{id}/sources` returns `{ source_signal_ids, signals[] }` for the latest preview draft’s citations, falling back to `sessions.state.source_signal_ids`. Session ownership matches other session routes (owner-only; not org-shared).
3. **Hydrated cards, not raw ids** — each `CitedSignal` is `{ signal_id, source, title, url, excerpt }` (admin Trace-equivalent fields). Missing rows are omitted from `signals` but ids stay on `source_signal_ids`.
4. **SSE enhancement** — `signals.updated` includes `signals[]`; `preview.updated` includes `source_signal_ids` + `sources[]`. Clients merge with REST; refresh rehydrates from `GET …/sources`.
5. **Surfaces** — Preview panel always shows the cited list when present. Chat/agent shows the same cards when the session already carries citations (research / grounding) even before a preview draft exists. Confirm / publish / catalog upsert stay HTTP and are not tools.

## Consequences

- Frontend must not dump session JSON as the trace UX.
- Admin Session Trace remains the ops debugger (node steps, LLM records); end-user links do not replace it.
- Extending `CitedSignal` should go through `schemas/contracts.py` + `python -m scripts.export_contracts`.
