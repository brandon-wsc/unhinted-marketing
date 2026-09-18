# ADR 0022 — Real publish: Instagram adapter, org social accounts, receipt status machine

- **Status:** Accepted
- **Date:** 2026-09-02
- **Related:** [ADR 0003](./0003-confirm-without-llm.md) (Confirm / publish stay HTTP, zero LLM — unchanged); [ADR 0008](./0008-preview-images-append-only.md) (`media_ids` supply the publish image); [ADR 0020](./0020-org-byok-keys-models-routing.md) (Fernet credential-at-rest pattern reused for platform tokens); [ADR 0024](./0024-media-storage-local-and-s3.md) (Confirm derives publish URL from stored key)
- **Plan:** [docs/PUBLISH_PLAN.md](../PUBLISH_PLAN.md) (full design: schema, protocol, testing, PR slicing)

## Context

`POST /api/sessions/{id}/confirm` is a traditional handler ([ADR 0003](./0003-confirm-without-llm.md)) that today only writes a `tool_receipts` row with `status="stubbed"` — no platform call happens. ROADMAP locks the first publish platform as **Instagram via Meta Graph API** (Open Question #2) and targets real publish for Phase 4.

Two prerequisites were open:

1. **Where do platform credentials live?** Env vars (`META_IG_USER_ID` + token) can only carry a single tenant's single account. A multi-org product needs per-org credentials at rest — the same problem BYOK solved with `byok_providers` ([ADR 0020](./0020-org-byok-keys-models-routing.md)).
2. **What does Confirm do when the draft has no image?** The IG Content Publishing API requires media; a copy-only draft cannot be published to Instagram.

## Decision

### 1. `social_accounts` table — org-scoped, Fernet-encrypted tokens

One Alembic hex revision adds `social_accounts`, mirroring the `byok_providers` shape:

- `id`, `company_id` (FK `entities.id` ON DELETE CASCADE, indexed), `platform` (`CHECK platform IN ('instagram')`), `ig_user_id`, `access_token_encrypted` (Text, Fernet under `BYOK_ENCRYPTION_KEY`), `token_last4`, `expires_at`, `last_verified_at`, `last_error_kind`, `created_by` (FK `users.id` ON DELETE SET NULL), timestamps.
- Raw tokens are never logged, never serialized to API/SSE/OpenAPI — `token_last4` only, same posture as BYOK keys.
- Editors connect via Instagram Login on `/settings?tab=instagram` (see Consequences). CLI `python -m cmd.worker connect-social-account …` remains a bootstrap fallback, following the `set-platform-role` pattern.

Explicitly **not** built in the original slice: OAuth connect flow (added 2026-09-05 — see below), token auto-refresh scheduler (long-lived tokens last ~60 days; expiry is handled manually), a multi-platform abstraction layer (`platform` CHECK constraint is enough for one platform), and platform webhooks.

### 2. Publish adapter behind a feature flag

- `internal/tools/publish.py` exposes `publish_social_post(PublishSocialPostRequest) -> PublishSocialPostResponse`, consuming the shapes already locked in [`schemas/tools.py`](../../schemas/tools.py).
- Env `PUBLISH_ADAPTER=stub|instagram`, default `stub`. CI, dev, and tests never hit Meta unless explicitly opted in.
- The Instagram adapter implements the Graph two-phase publish on `graph.instagram.com`: `POST /{ig-user-id}/media` (container; requires a publicly reachable `image_url`) then `POST /{ig-user-id}/media_publish`. Token decryption reuses the BYOK Fernet helper ([`internal/llm/keys.py`](../../internal/llm/keys.py)).
- The publish image is the draft's first `media_ids` entry; Confirm derives a Meta-reachable URL via `resolve_external_url` (object key or leftover baked URL → current `WEB_BASE_URL` / CDN; browser preview uses relative `resolve_stored_url` — [ADR 0024](./0024-media-storage-local-and-s3.md)). Multi-image carousels are deferred. On-prem local disk is unreachable by Meta unless `WEB_BASE_URL` is public; on-prem S3-compatible behind `S3_PUBLIC_BASE_URL` or cloud S3/CDN satisfies it — unit tests mock httpx.

### 3. Copy-only drafts are rejected at Confirm

Instagram requires media. Confirm returns **400** for a draft without images, with a clear "add an image first" message. A stored object key counts as an image; `placeholder://` does not ([ADR 0024](./0024-media-storage-local-and-s3.md)). We do not silently fall back to a brand-default image and do not keep the old stub behavior of accepting everything.

### 4. Receipt status machine

`tool_receipts.status` moves from the single `stubbed` value to `pending` / `published` / `failed`:

- `published` — response payload carries the platform post ID and permalink.
- `failed` — `last_error_kind`-style classification (`token_expired` / `permission` / `platform_error`); the UI shows the reason. Platform 5xx/timeouts are **not** auto-retried inline — the user-private `idempotency_key` already guarantees a retried Confirm cannot double-publish.
- Container-status polling for mid-flow failures is deferred (no worker in this slice).
- SSE `confirm.completed` payload gains `status` and `permalink` so the receipt panel renders the real outcome.

### 5. Boundaries unchanged

Publishing still happens only in the Confirm handler with a valid per-revision `approval_token` ([ADR 0003](./0003-confirm-without-llm.md)). Chat/LangGraph never publish; publish is never registered as an in-loop tool. Idempotency stays user/session-scoped (IDOR protection unchanged).

## Consequences

- New routes surface no token material; the receipt panel exposes `status` / `permalink` / error reason only.
- Contracts (`docs/contracts/publish-social-post-*.schema.json`) are regenerated via `python -m scripts.export_contracts` when response fields change.
- `.env.example` gains `PUBLISH_ADAPTER` and `META_GRAPH_API_VERSION`.
**Added 2026-09-05 — Meta OAuth connect:** editor popup + poll; encrypted connect-state + CSRF cookie. **Update 2026-09-06 — Instagram Login:** dialog is `https://www.instagram.com/oauth/authorize` (not Facebook Login). Scopes: `instagram_business_basic`, `instagram_business_content_publish`. Exchange short-lived token at `api.instagram.com/oauth/access_token`, then `GET graph.instagram.com/access_token?grant_type=ig_exchange_token`. `ig_user_id` from `GET graph.instagram.com/me` (`user_id`, else `id`). Publish host `graph.instagram.com`. Failures: `meta_oauth_not_professional`, `meta_oauth_missing_publish`. `META_APP_ID` / `META_APP_SECRET` are the Instagram App ID / Secret. Data migration deletes Facebook-era `social_accounts` rows.

- Deferred (each needs its own slice, some a superseding ADR): token auto-refresh, FB/Threads platforms, carousels, per-day publish rate limits (ROADMAP Safety), container-status polling.
- Changing the credential-storage rule (§1), the copy-only rejection (§3), or the Confirm-only publish boundary (§5) requires a superseding ADR; adapter internals and UI arrangement may iterate without one.
