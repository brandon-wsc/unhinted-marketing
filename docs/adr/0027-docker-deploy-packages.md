# ADR 0027 — Docker deployment packages: all-in-one vs external-DB compose

- **Status:** Accepted
- **Date:** 2026-09-13
- **Supersedes:** —
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (mode baked into images), [ADR 0024](./0024-media-storage-local-and-s3.md) (local media root), [ADR 0026](./0026-onprem-first-run-setup.md) (first-run wizard), [ADR 0020](./0020-org-byok-keys-models-routing.md) (BYOK Fernet KEK)

## Context

Self-hosted users split into two shapes: operators who run their own Postgres
(backups, HA, upgrades are their job) and evaluators who want one command to a
running instance. Both are production installs — the difference is only where
the database lives. The existing root `docker-compose.yml` is a dev convenience
(pgvector + adminer) and does not run the app at all; migrations and secrets
were manual steps.

`APP_ENV=production` refuses the published-default `JWT_SECRET` and requires a
valid `BYOK_ENCRYPTION_KEY`, so a true one-command install needs secrets
materialized somewhere — without weakening the production checks.

## Decision

### 1. Two compose packages under `deploy/`

- `deploy/docker-compose.yml` — **all-in-one**: `db` (pgvector/pgvector:pg18,
  no published port) + `migrate` + `api` + `scheduler` + `web`. Works with no
  `.env`.
- `deploy/docker-compose.external-db.yml` — **external DB**: `migrate` +
  `api` + `scheduler` + `web`. `DATABASE_URL`, `JWT_SECRET`,
  `BYOK_ENCRYPTION_KEY`, `WEB_BASE_URL`, `CORS_ORIGINS` are required via
  `${VAR:?}` fail-fast interpolation; no auto-secrets.

Both run `APP_ENV=production`, `DEPLOYMENT_MODE=onprem` and share one backend
env block (YAML anchor). The web service is the only published port
(`WEB_PORT`, default 8080); nginx proxies `/api` to the service named `api`.

### 2. `migrate` one-shot service owns schema setup

A `migrate` service (api image, `command: alembic upgrade head`) runs before
`api`/`scheduler` via `depends_on: service_completed_successfully`. This keeps
migration out of the API boot path, stays safe if `api` is later scaled to
multiple replicas, and doubles as the secrets-init step in the all-in-one
package (it completes before readers start, so file generation cannot race).

### 3. `AUTO_SECRETS` — volume-persisted secret generation (all-in-one only)

`docker/api-entrypoint.sh` (the api image `ENTRYPOINT`) is inert unless
`AUTO_SECRETS=true`. When set, it sources `/app/data/.secrets.env` if present,
generates `JWT_SECRET` / `BYOK_ENCRYPTION_KEY` when absent, and rewrites the
file `chmod 600` on the shared `appdata` volume. The same file is read by api
and scheduler, so the whole stack shares one key pair across restarts.
Deleting `appdata` rotates both keys — documented blast radius identical to
losing `BYOK_ENCRYPTION_KEY` (ADR 0020). The external-DB package never sets
`AUTO_SECRETS`.

### 4. Image coordinates

Services declare `image: ${IMAGE_PREFIX:-ghcr.io/brandon-wsc}/unhinted-{api,web}:${IMAGE_TAG:-onprem}`
plus a `build:` section — repo checkouts build locally (`up -d --build`), and
the same files pull once images are published. `IMAGE_PREFIX` / `IMAGE_TAG`
override the namespace and tag without editing the files.

## Consequences

- `cd deploy && docker compose up -d --build` reaches `/setup` with zero env
  work; the wizard (ADR 0026) handles admin/org creation, so no CLI bootstrap.
- Operators get a compose that cannot boot without explicit secrets — no
  silently-generated keys in a production-by-choice deployment.
- Upgrading is `up -d --build` (or `pull && up -d`); `migrate` re-runs each
  time and is idempotent.
- Compose `service_completed_successfully` needs Docker Compose v2.20+.
- Root `docker-compose.yml` remains dev-only; the deploy `db` never mounts
  `docker/postgres/init` (test-database SQL is dev/test only).
- Publishing images to GHCR is follow-up CI work; until then both packages
  build from a checkout.
