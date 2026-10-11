# ADR 0043 — Publish image public URL: precondition gate, admin surface, provider-URL persist

## Status

Accepted

## Context

Media storage is local disk on-prem by default and S3 in cloud ([ADR 0024](0024-media-storage-local-and-s3.md), [ADR 0025](0025-db-storage-config-and-portal-migration.md)). Postgres stores the object key, not a URL: browser reads resolve via `resolve_stored_url` (local → relative `/api/media/{key}`, served unauthenticated; S3 → public/CDN URL), and Confirm resolves via `resolve_external_url`, which prefixes `instance_settings.web_base_url` for local keys. Instagram Graph requires a Meta-reachable `image_url` ([ADR 0022](0022-real-publish-instagram.md)); the constraint is documented in PUBLISH_PLAN §4 and the deploy README tunnel note, but never enforced or taught inside the app.

A review of the publish image URL surface found four gaps:

1. **Every URL-reachability failure collapses into `platform_error`** on a failed receipt — the operator cannot tell a config mistake from a Meta outage. `token_expired` and `permission` already have dedicated kinds; reachability does not.
2. **A private-looking `web_base_url` passes the current guard.** `_publish_instagram` only checks `startswith("http(s)://")`, so `http://192.168.x.x`, `http://localhost`, or a `.local` host sails through and fails later inside Meta's fetch — the worst case to diagnose because previews (`/api/media/` on the SPA origin) look fine the whole time.
3. **Admin surfaces never state the requirement.** The setup wizard and Platform → Instance URL hints cover invite links / OAuth redirects but not publish image fetch; the Instagram settings tab and the storage `publicUrl` field never explain why a public URL is needed.
4. **Provider `https://` image refs are stored as-is.** `persist_generated_image` passes provider URLs through, and `image_result_to_url` prefers `url` over `b64_json` when both exist. Provider-signed URLs expire (OpenAI ~1h), which kills the preview `<img>` *and* the Meta fetch; the bytes never enter the store, so GC refcounting, session-fork sharing, and local→S3 migration all bypass them — contradicting the "always persist real bytes" rule recorded in STATUS.

## Decision

### 1. `media_url_not_public` is a publish precondition

- Before the Instagram adapter calls Meta — on the shared path used by Confirm and by owner/admin approve ([ADR 0041](0041-member-usage-limits-and-publish-approval.md)) — the resolved `image_url` is classified. Obviously-unreachable shapes raise `PublishPreconditionError("media_url_not_public")`, the same plane as `social_account_not_connected`: fail fast, no `failed` receipt written, `approval_token` / idempotency semantics untouched, and the member can retry once an admin fixes config.
- Flagged shapes: empty/relative (`web_base_url` unset), private host (localhost, loopback, RFC-1918, link-local, `.local` / `.internal` hostnames), and non-TLS `http://` on a non-localhost host. Each variant carries a message naming the fix surface — Platform → Instance for `web_base_url`, Settings → Storage for the S3 public URL.
- Reachability is classified, not proven. A public-shaped URL behind a dead tunnel still reaches Meta and lands as `platform_error`; container-status and transport errors name reachability as a suspect in their message copy. Consistent with PUBLISH_PLAN §4 — the residual is documented, not coded around.
- The stub adapter is unaffected: it never fetches the image.

### 2. Provider `https://` image refs persist into the store at generation time

- `persist_generated_image` no longer returns provider URLs as-is. An `http(s)` ref is fetched server-side at generation time and written under the session object key; the stored ref is always our own object key. Content type is magic-sniffed and the key extension replaced, same as the `data:` path.
- A failed fetch or a non-image payload raises — the image-generation turn fails and surfaces that error. A dead external URL is never stored.
- The fetch is bounded: short timeout, byte cap, and no redirects onto private-IP/link-local targets (SSRF guard, consistent with the BYOK base-URL guard in [ADR 0020](0020-org-byok-keys-models-routing.md)).
- When a provider response carries both `url` and inline bytes, inline bytes win — they skip the fetch entirely. The URL path is only for providers that return no bytes.

### 3. Admin surfaces teach the requirement where the value is set

- i18n copy updates: `setup.instance.baseUrlHint` and `system.instance.baseUrlHint` state that the URL builds invite links, OAuth redirects, **and publish image URLs**, and that Instagram publish needs a public HTTPS origin Meta can fetch. The Instagram settings tab gains a hint tying publish to Instance URL or a storage public URL.
- Saving a private-looking `web_base_url` produces a **soft warning** (panel-level, not a hard rejection): LAN-only installs that never publish to Instagram are legitimate and must not be blocked.
- The deploy README tunnel note already covers the operator docs side; no further doc split.

### 4. Residual failure modes (recorded, not gated)

Pre-flight classification cannot detect, and this ADR deliberately does not try:

- a public-shaped but stale `web_base_url` (tunnel down, domain moved, wrong port);
- multi-worker on-prem local installs without a shared `MEDIA_ROOT` volume (Meta can hit a node that lacks the file);
- S3 without `public_base_url` falling back to an internal endpoint, or a bucket that is not public-read;
- leftover baked URLs in dev databases (old MinIO `http://127.0.0.1:9000/...`, pre-key storage refs — [ADR 0024](0024-media-storage-local-and-s3.md) documents these are not migrated);
- Meta-side fetch failures on genuinely public URLs.

These land as `platform_error` on the receipt; the message copy names reachability as a suspect so the operator knows where to look first.

## Consequences

- Config mistakes fail fast before Meta with an actionable error instead of a failed receipt that blames the platform.
- Generated and uploaded images share one lifecycle as store objects: stable preview, stable publish, GC, fork-sharing, and storage migration all apply uniformly. Provider signed-URL expiry stops being a failure mode.
- Operators learn the public-URL requirement in the same panel where they set the URL; the soft warning keeps private LAN installs usable.
- Accepting that reachability cannot be proven locally keeps the gate cheap and honest — we classify obvious misconfig and leave the rest to Meta with better error copy.
