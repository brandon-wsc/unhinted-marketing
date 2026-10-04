# ADR 0038 — Resolved source signals on preview payloads

- **Status:** Accepted
- **Date:** 2026-10-04
- **Supersedes:** — (extends [ADR 0001](./0001-preview-canonical-draft.md) canonical draft payload; completes ROADMAP DoD §7 UI half)

## Context

`grounding_check` already filters `source_signal_ids` and every `preview_drafts` revision persists them; `trend_searcher` emits a `signals.updated` event mid-turn. But the preview contract (`PreviewUpdatedData`) and the session snapshot carry only ids-at-most — `GET …/messages` has no preview block and `signals.updated` is ids-only and live-only, so after a refresh the SPA cannot show which HK signals a draft was grounded on. The admin Session Trace resolves ids server-side (`get_signals_by_ids`); the end-user pane had no equivalent.

## Decision

1. **`PreviewUpdatedData` gains `source_signals`** — resolved `{signal_id, source, title, url, excerpt}` objects in draft order, not raw ids. Resolved objects ride the payload so clients never join against `GET /api/signals/top` (a top-N list that may not contain an old revision's refs).
2. **Same field on `UpdateDraftResponse` + `PreviewMediaMutationResponse`** — every REST path that returns a revision echoes the resolved list, so a manual `POST /draft` or media mutation does not blank the Sources block until the next SSE event.
3. **`session.snapshot` gains `source_signals`** — resolved from the latest `preview_drafts` row (fallback `session.state.source_signal_ids` when no draft row exists). Refresh / reopen hydrates the same list as a live `preview.updated`.
4. **`signals.updated` stays ids-only.** It is a mid-turn notice; the authoritative list arrives with `preview.updated` / snapshot / REST responses.
5. **Resolution is best-effort.** Missing signal rows (wiped corpus, stale ids) are dropped from the list; lookup failure yields an empty list, never a failed preview payload. Ids still persist on `preview_drafts.source_signal_ids` — the payload is a read-side denormalization, not the record.
6. **Preview pane renders a Sources block** under the IG mock — one row per signal, title links to `url` when present, `source` shown alongside. Read-only; editing copy does not edit grounding (that is the reviewer/grounding path, [ADR 0009](./0009-research-gate-and-tavily-ingest.md)).

## Consequences

- DoD §7 is closed end-to-end: graph grounding (already ✅) + visible trace links in the session UI.
- Old clients ignore `source_signals` (additive field); new clients on old backends see no Sources block.
- Signal rows are the same rows the admin trace resolves — one lookup helper (`resolve_source_signals`) serves both.
- Payload size stays small: ids are capped upstream (~8) and only display fields are denormalized, never `metrics`.
