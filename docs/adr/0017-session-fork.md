# ADR 0017 — Session fork (branch a chat at an assistant message)

- **Status:** Accepted
- **Date:** 2026-08-24
- **Related:** [ADR 0008](./0008-preview-images-append-only.md) (append-only preview images), [ADR 0024](./0024-media-storage-local-and-s3.md) (session-delete GC refcounts shared fork asset keys)

## Context

Users want to branch a conversation Gemini-style: from any assistant message, spin off a new chat that carries the transcript up to that point (and the work-in-progress preview draft) so they can explore a different direction without polluting the original session.

Constraints from existing ADRs: confirm/publish stays HTTP-only with a per-revision `approval_token` ([ADR 0003](./0003-confirm-without-llm.md)); preview images are append-only per session with drafts referencing `media_ids` ([ADR 0008](./0008-preview-images-append-only.md)); sessions/drafts/media are user-private ([ADR 0010](./0010-org-membership-invites-and-shared-assets.md) §5).

## Decision

1. **Fork is a plain HTTP endpoint**, not a graph node: `POST /api/sessions/{id}/fork` with `{ message_id }`. Ownership rules unchanged (`_require_owned_session`); the message must belong to the session.
2. **Transcript copy.** The new session gets new `session_messages` rows (new UUIDs, same role/content/metadata) for every message up to and including the fork point, sliced by message id from the ordered list (there is no `seq` column). Copied `metadata.agent_actions` anchors (`afterMessageId`) reference old ids and simply do not render in the fork.
3. **Draft + media copy, time-aligned, fresh approval token.** The fork copies the `preview_drafts` revision that existed **at the fork-point message's `created_at`** (`created_at <=` that timestamp, latest revision wins) — not necessarily the source's latest. If no draft existed yet at the fork point, the fork carries no preview, even when the source later produces one; edits made after the fork-point message do not travel (message-anchored, deliberate). Same-turn message + draft rows share one transaction timestamp, so `<=` includes the preview produced by that exact turn. The copied row restarts as `revision=1`, keeps the source row's `created_at` (so fork-of-fork stays time-aligned against the copied messages, which also keep their original `created_at`), and gets a **newly minted** `approval_token` (`secrets.token_urlsafe(24)`, same as any new revision) — the token is never shared across sessions. `preview_images` rows are duplicated into the new session (same asset URLs; new rows are still append-only per ADR 0008) and `media_ids` are remapped to the new row ids. Draft fields land in the new session's `state`; `mode=PREVIEW` only when the source was in PREVIEW. Never copied: `pending_confirm`, `awaiting_image_ok`, `turn_discard`, `brief`, `status` (fork starts `active`, unpinned).
4. **Lineage columns on `sessions`:** `forked_from_session_id` (FK, `ON DELETE SET NULL`), `forked_from_message_id` (plain UUID, no FK — messages cascade-delete with their session), `forked_from_title` (snapshot so the label survives source rename/delete; live title preferred when the source exists).
5. **Naming:** fork title = `"(n) base"` where `base` is the source display title with any leading `"(n) "` prefix stripped, and `n` = count of existing forks **of the direct source session** + 1. Fork-of-fork may collide with a sibling's name; cosmetic only, user-renameable.
6. **Lineage read-back on `GET …/messages`** (REST SSOT, ADR 0002): session-level `forked_from { session_id, message_id, title }` and per-message `forks: [{ session_id, title, created_at }]` for messages that were forked. No SSE events for fork. `forked_from_message_id` always refers to the **source** message; the fork-point copy inside the new session carries `metadata.fork_point: true` so the client can place the divider (copied messages get new ids). Copied messages keep their original `created_at` so the forked timeline stays ordered and timestamps stay truthful.
7. **UI:** fork button on assistant messages only (copy → fork → time). New chat shows a divider after the last copied message: "Forked from {source title}". Source message shows a chip — one fork: "Forked to {title}"; several: "Forked to {n} chats" — opening a menu that jumps to each fork. The fork response (`ForkSessionResponse`) adds `preview_note` so the client toasts **only** the surprising outcomes of the time-aligned copy: `carried_stale` (fork kept the fork-point revision; source has newer edits) and `not_carried_later` (source has a preview but it postdates the fork point, so the fork has none). `null` = nothing to say.
8. **Fork during an in-flight turn is allowed**; only persisted messages are copied (streaming text is not in the DB yet). The fork gets a fresh LangGraph checkpoint (`thread_id` = new session id); the next turn rebuilds history from the copied DB messages + state.

## Consequences

- Two sessions never share an `approval_token`; confirm safety (ADR 0003) is preserved by construction.
- Fork preview is message-anchored: forking at an older message never carries newer draft edits, and forking before any preview existed carries none. The client surfaces both via `preview_note` toasts instead of silently diverging.
- Time-alignment relies on `preview_drafts.created_at` ordering; same-transaction writes (turn persist) share a timestamp, so `<=` is the correct inclusive bound.
- Deleting the source session leaves forks intact (`SET NULL` + title snapshot); the source's "Forked to" chips disappear with it. Shared preview object keys stay until the last referencing session is deleted ([ADR 0024](./0024-media-storage-local-and-s3.md) refcount GC).
- Fork lineage is queryable in both directions from `sessions` alone; no separate table.
- Fork count/title resolution adds one indexed query to `GET …/messages`.
