# ADR 0024 — Media storage: local default on-prem (optional S3-compatible), AWS S3 in cloud

- **Status:** Accepted
- **Date:** 2026-09-09
- **Supersedes:** —
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (deployment mode selects the backend), [ADR 0006](./0006-api-path-prefix-and-spa-proxy.md) (`GET /api/media/{key}`), [ADR 0008](./0008-preview-images-append-only.md) (append-only `preview_images`), [ADR 0017](./0017-session-fork.md) (fork shares asset URLs; GC refcounts), [ADR 0022](./0022-real-publish-instagram.md) (Confirm image URL)

## Context

Preview images (upload + LLM `data:` results) were stored through a single
boto3 client that required `S3_ENDPOINT_URL` plus static keys. Local/dev was
documented as MinIO. When that was missing, uploads became `placeholder://`
URLs and generated `data:` blobs stayed in Postgres — neither is usable in the
browser.

On-prem must work with zero extra infrastructure: local disk is the default.
But local disk caps on-prem at a single node sharing one volume. Peer
self-hosted products (GitLab, Nextcloud, Strapi, Directus, Payload, Mastodon,
Laravel/Rails/Django apps) all treat an S3-compatible endpoint as the normal
on-prem scale path while keeping local FS as the single-node default — we
follow that convention. MinIO Community Edition was archived/EOL in 2026, so
we document "**S3-compatible**" (Garage, SeaweedFS, RustFS, Cloudflare R2,
etc.) as a protocol, not a product: no MinIO branding, no required MinIO
docker-compose service. Cloud uses real AWS S3.
[ADR 0023](./0023-deployment-mode-flag.md) already distinguishes the two
deployment shapes; this is the first **behavior** branch on that flag.

Two more pressures are settled here so the storage story lives in one place:
what Postgres persists for each image (a baked origin URL breaks when domains
or CDNs change), and when bytes are reclaimed (append-only regen rows
otherwise leak files forever).

## Decision

### 1. Backend follows `DEPLOYMENT_MODE`; on-prem S3 is env-presence opt-in

No `STORAGE_BACKEND` flag. `DEPLOYMENT_MODE` already picks the family; within
on-prem, the presence of a complete S3 env set opts in. A second enum could
contradict the mode (e.g. `STORAGE_BACKEND=s3` with `DEPLOYMENT_MODE=onprem`
and no endpoint, or `local` in `cloud`) — deriving from mode + env keeps one
source of truth.

- **`onprem` (default):** local filesystem store under `MEDIA_ROOT` (default
  `data/media`). Zero extra env for media.
- **`onprem` + S3-compatible (optional):** when `S3_BUCKET` **and**
  `S3_ENDPOINT_URL` are both set, use the same S3 store as cloud via boto3
  `endpoint_url` with **path-style** addressing (required by Garage /
  SeaweedFS / RustFS / R2-style endpoints). Setting only one of the two fails
  at process start — never silently fall back to local disk after the
  operator asked for object storage.
- **`cloud`:** AWS S3. Require `S3_BUCKET`. `S3_ENDPOINT_URL` is honored here
  too — custom endpoint is a property of the single shared S3 driver, not an
  on-prem-only feature (e.g. Cloudflare R2 in front of a cloud deploy).
  Without an endpoint, boto3's default AWS endpoint and addressing apply.
- Credentials (both modes): `S3_ACCESS_KEY` + `S3_SECRET_KEY` must both be
  set, or both omitted to use the default boto3 chain (instance role). Missing
  bucket where required, or only one of the two keys, fails at process start.

### 2. One facade, two implementations

Callers keep `put_bytes` / `persist_generated_image` / `media_object_key`.
`put_bytes` returns a browser-fetchable URL for convenience; **Postgres does
not store that return value** — store-backed rows persist the object key
(§3). `persist_generated_image` for `data:` returns the key.

- Local: `{WEB_BASE_URL}/api/media/{key}` (relative `/api/media/{key}` if
  `WEB_BASE_URL` is empty). Unauthenticated `GET /api/media/{key:path}` streams
  the file (same public-read model as the old MinIO anonymous download; path
  traversal rejected). Signed / private URLs stay STATUS hardening and still
  derive from the key.
- S3: `S3_PUBLIC_BASE_URL/{key}` if set, else `{S3_ENDPOINT_URL}/{bucket}/{key}`
  when an endpoint is configured (path-style), else
  `https://{bucket}.s3.{region}.amazonaws.com/{key}`. Do not auto-create the
  bucket or attach a public-read policy — ops owns the bucket/CDN.

### 3. Store object keys in Postgres; derive URLs at read

Store-backed uploads and `data:` generation results persist the **object key**
(`sessions/{id}/r{revision}-{hex}.{ext}`) in `preview_images.url` and
`preview_drafts.image_url` (and graph `image_url` during a turn) — not a baked
origin, and not `put_bytes`'s returned URL. Provider-hosted `http(s)://` and
`placeholder://` mocks stay as full URLs — they are not objects in our store.
The short token (`r{revision}-{hex}`) means concurrent regen/upload can never
overwrite the same bytes.

`resolve_stored_url` is the read choke point and derives the current URL:

- object key → current `MediaStore.public_url(key)`
- legacy `{origin}/api/media/{key}` or relative `/api/media/{key}` → peel key,
  re-derive
- legacy URL under the current `S3_PUBLIC_BASE_URL`, the configured endpoint's
  path-style base (`{endpoint}/{bucket}/`), or virtual-hosted
  `https://{bucket}.s3.{region}.amazonaws.com/` → peel key, re-derive
- provider `http(s)://`, `placeholder://`, `data:` → as-is (not our objects)

Callers: `media_item_payload`, `preview.updated` / snapshot `image_url`,
Confirm's publish image URL. Confirm's copy-only gate treats a bare object
key as an image (`http(s)` / `data:image/` / valid key all count;
`placeholder://` does not). The HTTP/SSE contract is unchanged — clients
still receive a browser-fetchable `url` / `image_url`. Changing
`WEB_BASE_URL` or `S3_PUBLIC_BASE_URL` applies to old rows on the next read.
No new column, no backfill migration.

### 4. Always persist real bytes

On-prem local disk is always available, so uploads and `data:` generation
results are always written. Uploads are capped (10 MB) with PNG/JPEG magic
sniffing; `persist_generated_image` rejects unknown schemes (not `http(s)` /
`data:`). LLM **no-credentials** / `LLM_IMAGE_MODEL=placeholder` mock URLs in
the image-gen node stay — those are not a storage fallback.

### 5. Eager GC on session delete; no sweeper

`MediaStore.delete(key)` on both backends: local `unlink(missing_ok=True)`
plus empty-parent pruning up to `MEDIA_ROOT`; S3 `delete_object` (idempotent —
`NotFound` / `NoSuchKey` is success).

`DELETE /api/sessions/{id}` collects the session's media keys **before** the
DB delete (from `preview_images.url` and `preview_drafts.image_url`, peeled
through `extract_store_key` so legacy baked URLs still count; `http(s)://`,
`placeholder://`, and `data:` refs are skipped). After commit it **refcounts**
each collected key against remaining `preview_images.url` /
`preview_drafts.image_url` (same peel): a key still referenced by any other
session is skipped. Fork copies keep the source's asset URLs ([ADR 0017](./0017-session-fork.md));
deleting the source (or a fork) must not reclaim bytes the other session
still serves. Only refcount-zero keys are deleted, best-effort: a failed
object delete logs a warning and never blocks the response; a failed collect
still commits the session delete and skips reclaim.

Crash leftovers (`put_bytes` then process death before the row insert; eager
delete itself failing) stay on disk — operators wipe `MEDIA_ROOT` / the bucket
prefix if needed. No periodic sweeper, no new env, no `iter_keys` walk; a
sweeper can be a later ADR if production leak volume warrants it.

## Consequences

- Operators `docker compose up` Postgres only; no required object-storage
  sidecar. On-prem scale-out (multi-node, no shared volume) is an S3-compatible
  endpoint away — same facade, no code branch.
- Existing MinIO object bytes and `http://127.0.0.1:9000/...` URLs in a local
  DB are not migrated (dev-only; they 404 after the switch).
- Instagram Confirm still needs a Meta-reachable HTTPS URL. On-prem local disk
  has the same limitation MinIO had: `WEB_BASE_URL` must be public (tunnel) or
  publish stays stub. On-prem S3-compatible behind a public
  `S3_PUBLIC_BASE_URL`, or cloud S3/CDN, satisfies it.
- On-prem multi-worker on local disk needs a shared `MEDIA_ROOT` volume; that
  is an operator concern, not an app-level second store — or set
  `S3_ENDPOINT_URL` and share a bucket instead.
- Graph / DB may hold a bare object key; leaking it to `<img src>` without
  `resolve_stored_url` would fail — tests cover the HTTP/SSE emit paths.
- Live-session regen / re-upload still accumulates files until the session is
  deleted (append-only, unchanged).
- Crash-safety invariant: orphan bytes are acceptable; dangling references are
  not. Object delete runs *after* the DB commit, never before. Shared fork
  objects live until the last referencing session is deleted.
