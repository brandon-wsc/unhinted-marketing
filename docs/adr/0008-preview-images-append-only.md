# ADR 0008 — Append-only preview images + draft media_ids

- **Status:** Accepted
- **Date:** 2026-08-05
- **Supersedes:** Partial — extends [ADR 0001](./0001-preview-canonical-draft.md) media shape (`image_url` → `media_ids` + `preview_images`); copy fields unchanged
- **Amended by:** [ADR 0025](./0025-store-media-object-keys.md) — `url` column stores an object key (or external/placeholder URL); HTTP/SSE still expose a fetchable `url`

## Context

Preview assumed a single `preview_drafts.image_url` (+ `image_plan`). We need multiple images, editable generation plans (user + AI), and formats such as `comic_4panel`, without losing Confirm/revision integrity.

In-place UPDATE + trigger log tables were rejected for publishable state: `approval_token` must bind a frozen composition.

## Decision

1. **Strategy: any publishable change → new `preview_drafts` row** (existing revision + new `approval_token`). Caption-only edits may **reuse** the same `media_ids`.
2. **`preview_images`** — session-scoped, **append-only** asset versions:
   - Columns: `id`, `session_id`, `seq`, `role`, `format`, `status`, `url`, `plan` (JSONB), `created_at`
   - Change plan / regen / add / replace image → **INSERT** a new row (do not mutate plan/url of a row already referenced by a draft). `status` may move to `failed` without rewriting plan.
3. **`preview_drafts.media_ids`** — ordered `uuid[]` referencing `preview_images.id` (composition record). No join table for MVP.
4. **Compat:** keep `image_url` / `image_plan` on `preview_drafts` as denormalized primary (`media_ids[0]`) until FE/API fully switch; SSE/API may expose both `image_url` and `media[]`.
5. **Not in this ADR:** image slot parent table; trigger-based history. Plan-edit / add-image HTTP + Preview UI shipped as follow-up on ADR 0008.

## Consequences

- Confirm continues to validate a specific draft revision; resolve images via that row’s `media_ids`.
- Orphan image rows (never referenced) are allowed; purge is a later ops concern.
- Graph may still carry `image_url` / `image_plan` in state during a turn; persist must dual-write into `preview_images` + `media_ids`.
