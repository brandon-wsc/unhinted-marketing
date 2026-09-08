# ADR 0024 — Media storage: local disk on-prem, AWS S3 in cloud

- **Status:** Accepted
- **Date:** 2026-09-08
- **Supersedes:** —
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (deployment mode selects the backend), [ADR 0006](./0006-api-path-prefix-and-spa-proxy.md) (`GET /api/media/{key}`), [ADR 0008](./0008-preview-images-append-only.md) (`preview_images.url`), [ADR 0022](./0022-real-publish-instagram.md) (Confirm image URL), [ADR 0025](./0025-store-media-object-keys.md) (store keys, derive URLs at read)

## Context

Preview images (upload + LLM `data:` results) were stored through a single boto3
client that required `S3_ENDPOINT_URL` plus static keys. Local/dev was
documented as MinIO. When that was missing, uploads became `placeholder://`
URLs and generated `data:` blobs stayed in Postgres — neither is usable in the
browser.

On-prem operators should not run MinIO (or any S3-compatible sidecar). Cloud
should use real AWS S3. [ADR 0023](./0023-deployment-mode-flag.md) already
distinguishes the two shapes; this is the first **behavior** branch on that flag.

## Decision

### 1. Backend follows `DEPLOYMENT_MODE`

No `STORAGE_BACKEND` flag. No S3-compatible custom endpoint (`S3_ENDPOINT_URL`
is removed).

- **`onprem` (default):** always a local filesystem store under `MEDIA_ROOT`
  (default `data/media`). Leftover `S3_*` env is ignored. Zero extra env for
  media.
- **`cloud`:** always AWS S3 (boto3 default endpoint). Require `S3_BUCKET`.
  Credentials are `S3_ACCESS_KEY` + `S3_SECRET_KEY`, or both omitted to use the
  default boto3 chain (instance role). Missing bucket, or only one of the two
  keys, fails at process start — never silently write local disk on ephemeral
  cloud volumes.

### 2. One facade, two implementations

Callers keep `put_bytes` / `persist_generated_image` / `media_object_key`.
`MediaStore.put_bytes` returns a browser-fetchable URL stored on
`preview_images.url`.

- Local: `{WEB_BASE_URL}/api/media/{key}` (relative `/api/media/{key}` if
  `WEB_BASE_URL` is empty). Unauthenticated `GET /api/media/{key:path}` streams
  the file (same public-read model as the old MinIO anonymous download; path
  traversal rejected). Signed / private URLs stay STATUS hardening.
- S3: `S3_PUBLIC_BASE_URL/{key}` if set, else
  `https://{bucket}.s3.{region}.amazonaws.com/{key}`. Do not auto-create the
  bucket or attach a public-read policy — cloud ops owns the bucket/CDN.

### 3. Always persist real bytes

On-prem local disk is always available, so uploads and `data:` generation
results are always written. LLM **no-credentials** / `LLM_IMAGE_MODEL=placeholder`
mock URLs in the image-gen node stay — those are not a storage fallback.

## Consequences

- Operators `docker compose up` Postgres only; no MinIO service.
- Existing MinIO object bytes and `http://127.0.0.1:9000/...` URLs in a local
  DB are not migrated (dev-only; they 404 after the switch).
- Instagram Confirm still needs a Meta-reachable HTTPS URL. On-prem is the same
  limitation MinIO had: `WEB_BASE_URL` must be public (tunnel) or publish stays
  stub. Cloud uses the S3/CDN URL.
- On-prem multi-worker needs a shared `MEDIA_ROOT` volume; that is an operator
  concern, not an app-level second store.
