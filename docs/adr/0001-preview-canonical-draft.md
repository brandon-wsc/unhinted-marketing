# ADR 0001 — Preview Mode canonical draft

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** —

## Context

Preview must support Instagram (MVP) and later Meta sibling skins without forking copy per platform. AI and the user both edit the same draft. A free-form markdown editor would diverge from platform publish payloads.

## Decision

1. **Canonical draft copy** is shared: `{ caption, hashtags, cta }`, plus `image_url` on the preview payload (not duplicated per platform).
2. **MVP chrome** is Instagram only; Facebook / Threads later swap presentation on the same fields.
3. **AI edits** go through chat `revise` (reviewer-gated). **User edits** use `POST /sessions/{id}/draft` (no LLM) and mint a new `approval_token` / revision.
4. Confirm may auto-flush dirty local fields (`POST /draft` then `POST /confirm`). Optional Apply saves a revision without publishing.
5. Chat「可以出」does **not** publish — UI Confirm only (see ADR 0003).

Schema SSOT: `DraftCopy` / `PreviewUpdatedData` in `schemas/contracts.py` (JSON Schema under `docs/contracts/`).

## Consequences

- FE and BE must not invent per-platform caption trees for MVP.
- Platform switcher is chrome-only until a later ADR.
- Deferred: real image gen, Meta Graph publish, multi-platform switcher (STATUS).
