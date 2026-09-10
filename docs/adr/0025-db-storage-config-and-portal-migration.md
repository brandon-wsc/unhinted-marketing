# ADR 0025 — DB-backed storage config and portal-driven local→S3 migration

- **Status:** Accepted
- **Date:** 2026-09-10
- **Supersedes:** [ADR 0024](./0024-media-storage-local-and-s3.md) §1 (env-presence backend selection)
- **Related:** [ADR 0024](./0024-media-storage-local-and-s3.md) (§2–§5 unchanged: facade, object keys, persist, GC), [ADR 0023](./0023-deployment-mode-flag.md) (`DEPLOYMENT_MODE` still selects the family), [ADR 0020](./0020-org-byok-keys-models-routing.md) (Fernet-at-rest for secrets)

## Context

ADR 0024 made local disk the on-prem default and S3 an env-presence opt-in.
That is the right store split, but operators who start on local disk and later
need object storage have no in-app path: they must edit env, restart, and
manually copy bytes. Peer products either flip a flag after an out-of-band
`aws s3 sync` (Mattermost, Mastodon) or run an app CLI that copies then
rewrites URLs (GitLab, Discourse). Nextcloud's trap — enabling primary
`objectstore` without rewriting DB refs — makes old files inaccessible.

We already store **object keys** in Postgres and derive URLs at read
(ADR 0024 §3). That means a local→S3 copy can keep the same keys and flip
without rewriting any media row. The remaining gap is: config must live in
the DB so the portal can drive the switch, and the copy must not block
reads or writes.

## Decision

### 1. Config in DB; env is seed-only

`storage_configs` is the only source of truth for the active media backend.
Env `S3_*` vars may insert the first row on boot (`seeded_from_env`) when no
row exists; after that they are ignored. Incomplete env no longer fails at
process start — `assert_media_storage_config` becomes a first-use / portal
test-connection check.

`DEPLOYMENT_MODE` still selects the family ([ADR 0023](./0023-deployment-mode-flag.md)):

- **`onprem`:** default backend `local` under `MEDIA_ROOT`. Portal may save
  an S3-compatible target (bucket + endpoint) and migrate.
- **`cloud`:** backend is `s3`. Bucket is required on the active config
  (seeded from env on first boot, or saved in the portal). Local disk is not
  a cloud option.

Credentials reuse the BYOK Fernet KEK (`secret_key_encrypted`). Responses
never include the raw secret (last4 only, like BYOK).

### 2. Deployment-wide active config; schema is per-company

v1 has **one** active config for the whole instance — all companies flip
together. The table still has a nullable `company_id` so a later ADR can
split buckets without a schema rewrite. Storage facade signatures do **not**
take `company_id` in this ADR.

Partial unique index: at most one `active` row.

### 3. Dual-write, zero blocking

From migration start until cleanup completes, `put_bytes` and `delete_key`
hit **both** stores. Local is authoritative until flip (a local write
failure raises; an S3 write failure logs and is recovered by the verify
pass). After flip, S3 is authoritative and dual-write continues so
rollback remains free.

Invariant: **local is a complete superset of every store-backed key until
cleanup**. The read path (`resolve_stored_url` → `public_url`) is unchanged
until the active-backend flag flips. Upload, gen/edit, fork, Confirm, and
session-delete GC all stay available.

### 4. Leased in-process migration; human flip gate

A `storage_migrations` row plus `migration_done_keys` (per-key truth)
drive a DB-leased background loop. Any API process may claim the lease
(`lease_expires_at`); crash resume is cursor + done-keys, not a queue.

```
validating → copying → verifying → ready_to_flip → flipping → completed
                                                     → cleaning → done
any state → failed (retryable from checkpoint)
```

- **validating:** probe put + head + delete against the target bucket.
- **copying:** enumerate keys by scanning `preview_images.url` and
  `preview_drafts.image_url` through `extract_store_key` (same peel as GC).
  Filesystem orphans under `MEDIA_ROOT` are counted, not copied.
- **verifying:** same scan again (in-flight turns, TTL-stale workers,
  transient S3 failures). `missing == 0` → `ready_to_flip`. Persistent
  target-unreachable stays in `verifying` with backoff; the app keeps
  serving from local.
- **ready_to_flip:** human gate in company settings.
- **flipping:** one transaction activates the S3 config row.
- **cleaning:** optional, human-triggered, may wait days. Deletes local
  files whose key is in `migration_done_keys` (whitelist). Ends dual-write.
- **rollback:** available until cleaning completes — reactivate the local
  config row. Dual-write kept both sides complete.

Config cache is a 5–10s TTL. Staleness is safe because both stores hold
all bytes during the dual-write window.

### 5. Portal, not env, drives the switch

Company-settings editors (`owner` / `admin`) save S3 settings, test
connection, start migration, watch progress, flip, roll back, and clean.
Routes live under `/api/companies/{id}/storage/…`. Chat phrases never
trigger migrate or flip.

`GET /api/media/{key}` may keep serving local leftovers while a migration
is `completed` (pre-cleaning) so bookmarked local URLs survive the grace
window.

## Consequences

- Operators who started on local disk migrate from the portal with no
  restart and no downtime.
- ADR 0024 §2–§5 stay: object keys in Postgres, URL derive at read, always
  persist real bytes, eager GC on session delete.
- Cloud still requires a bucket; the requirement moves from process-start
  env check to the active DB row (seeded from env on first boot).
- Per-company buckets stay a later ADR (column present, unused).
- No periodic sweeper (unchanged). Legacy MinIO baked URLs stay
  unmigrated (dev-only, ADR 0024).
