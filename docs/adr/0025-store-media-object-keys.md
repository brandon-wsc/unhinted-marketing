# ADR 0025 — Store media object keys; derive URLs at read

- **Status:** Accepted
- **Date:** 2026-09-08
- **Supersedes:** Partial — [ADR 0024](./0024-media-storage-local-and-s3.md) §2 (“`put_bytes` return value is stored on `preview_images.url`”); [ADR 0008](./0008-preview-images-append-only.md) stored `url` column semantics (HTTP/SSE still expose a fetchable `url`)
- **Related:** [ADR 0001](./0001-preview-canonical-draft.md) (`image_url` on the preview payload), [ADR 0022](./0022-real-publish-instagram.md) (Confirm image URL)

## Context

[ADR 0024](./0024-media-storage-local-and-s3.md) persisted the browser-facing URL
returned by `put_bytes` onto `preview_images.url` (and the denormalized
`preview_drafts.image_url`). On-prem that URL includes `WEB_BASE_URL`; cloud
includes the S3 / CDN origin. Changing domain, turning on a tunnel, or
pointing `S3_PUBLIC_BASE_URL` at CloudFront left old rows 404ing even though
the bytes were still on disk / in the bucket.

The HTTP/SSE contract (`url` / `image_url` as a fetchable address) is unchanged
— only what Postgres stores.

## Decision

### 1. Store a ref, not a baked origin

Store-backed uploads and `data:` generation results persist the **object key**
(`sessions/{id}/r{revision}-{hex}.{ext}`) in `preview_images.url` and
`preview_drafts.image_url` (and graph `image_url` during a turn).

Provider-hosted `http(s)://` results and `placeholder://` mocks stay as full
URLs — they are not objects in our store.

No new column. No backfill migration. Existing baked URLs keep working via §2.

### 2. Derive at every client / publish read

`resolve_stored_url` (in `internal/media/storage.py`) is the read choke point:

- object key → current `MediaStore.public_url(key)`
- legacy `{origin}/api/media/{key}` or relative `/api/media/{key}` → peel key,
  re-derive
- legacy URL under the current `S3_PUBLIC_BASE_URL` or virtual-hosted
  `https://{bucket}.s3.{region}.amazonaws.com/` → peel key, re-derive
- other `http(s)://`, `placeholder://`, `data:` → as-is

Callers: `media_item_payload`, `preview.updated` / snapshot `image_url`,
Confirm’s publish image URL. Old MinIO `http://127.0.0.1:9000/…` URLs are
**not** rewritten (same as ADR 0024: not migrated).

### 3. API contract unchanged

Clients still receive a browser-fetchable `url` / `image_url`. Instagram
Confirm still needs that URL to be Meta-reachable (public `WEB_BASE_URL` or
cloud S3 / CDN).

## Consequences

- Changing `WEB_BASE_URL` or `S3_PUBLIC_BASE_URL` applies to old store-backed
  rows on the next read.
- Graph / DB may hold a key; leaking it to `<img src>` without resolve would
  fail — tests cover HTTP/SSE emit paths.
- Signed / private URLs stay STATUS hardening and still derive from the key.
