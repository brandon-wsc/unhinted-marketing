# ADR 0044 — Hosted Azure demo: azd + Container Apps + external Postgres

- **Status:** Accepted
- **Date:** 2026-10-11
- **Supersedes:** —
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (on-prem mode kept), [ADR 0024](./0024-media-storage-local-and-s3.md) (local media → Azure Files), [ADR 0027](./0027-docker-deploy-packages.md) (compose packages unchanged), [ADR 0037](./0037-demo-local-cd.md) (demo update tracks), [ADR 0039](./0039-postgres-job-queue.md) (worker/scheduler as services)

## Context

The existing deploy story is Docker-only: two compose packages for self-hosting
(ADR 0027) and a local/demo track on a single machine (ADR 0037). We wanted a
**hosted demo** on Azure that is not "a VM running compose" — serverless
containers and an external managed Postgres, at demo-scale cost
(~USD 35–65/mo vs ~USD 100 for an always-on VM), with HTTPS and a custom
domain (`demo.unhinted.hk`) so Instagram OAuth and public media URLs behave.

Constraints carried over: the product contract (REST SSOT + SSE, `/api`
prefix, media under `MEDIA_ROOT`) is unchanged; only the substrate differs.
The published GHCR images (`unhinted-{api,web}:onprem`) must be usable as-is —
no Azure-specific image builds.

## Decision

### 1. azd + Bicep, one resource group

`azure.yaml` + `infra/main.bicep` deploy a Consumption Container Apps
environment containing the same four roles as the compose package:

| Container Apps resource | Compose counterpart | Notes |
|-------------------------|--------------------|-------|
| `web` app — external ingress :80 | `web` | Stock GHCR nginx image |
| `api` app — internal ingress :8000 | `api` | Not reachable from the internet |
| `scheduler` app — no ingress | `scheduler` | Pinned to 1 replica |
| `worker` app — no ingress | `worker` | Pinned to 1 replica |
| `migrate` **Job** (Manual trigger) | `migrate` one-shot | `alembic upgrade head`, started by the post-provision hook |

Postgres is **external** — `DATABASE_URL` points at Neon (or any managed
Postgres with `vector`). There is no bundled `db` resource. The direct
endpoint is required, not a transaction-mode pooler: the worker claims jobs
with `FOR UPDATE SKIP LOCKED` and asyncpg caches prepared statements.

### 2. Secrets are ACA secrets, not AUTO_SECRETS

`DATABASE_URL` / `JWT_SECRET` / `BYOK_ENCRYPTION_KEY` are azd env values →
Bicep secure params → ACA `secretRef` env vars. `AUTO_SECRETS` stays off
(the `appdata` volume trick only works inside one compose host). Optional
`OPENAI_API_KEY` / `TAVILY_API_KEY` are injected only when non-empty.

### 3. Media = local backend on a shared Azure Files share

`DEPLOYMENT_MODE=onprem` is kept, so storage defaults to local disk under
`MEDIA_ROOT=/app/data/media` — backed by an Azure Files share mounted on the
`api` and `worker` apps (the same share, so worker-written files are
api-readable). `DEPLOYMENT_MODE=cloud` is *not* used: it would require an S3
backend, and Azure Blob is not S3-compatible (ADR 0024).

### 4. nginx upstream via the stock image's envsubst hook

The stock web image hardcodes `proxy_pass http://api:8000` (compose DNS, no
ingress). ACA internal ingress listens on port 80 and the api app is
addressed by FQDN, so `deploy/azure/nginx/default.conf.template` is uploaded
to a second Files share (`nginx-conf`) mounted at `/etc/nginx/templates`.
The official nginx entrypoint envsubsts `*.template` into `conf.d` at start,
with `API_UPSTREAM` set by Bicep to the api app's internal FQDN. No image
rebuild; the on-prem `web/nginx.conf` is untouched.

### 5. This is a demo track, not a third customer package

Customer installs stay on the compose packages + release compose assets
(ADR 0027, ADR 0037). The Azure recipe is for hosted demos / evaluation;
`IMAGE_TAG` pins a release (`v*`) while the floating `onprem` tag tracks the
latest release.

## Consequences

- `azd up` is the whole bring-up; `azd down` tears it down. Cost is driven by
  replica-hours — web/api minReplicas=1 avoids cold starts during demos
  (idle-rate billing); scaling to zero is a one-line Bicep change if the
  host sleeps for long stretches.
- First boot seeds `instance_settings` from `WEB_BASE_URL` (ADR 0026) — set
  it to the final public URL before the first boot or fix it later in
  Platform → Instance.
- Custom domain + cert: ACA managed certificates are free; only DNS records
  (CNAME + `asuid` TXT) are needed.
- Single-point-of-failure is accepted (1 replica each, no zone redundancy,
  no HA Postgres) — it is a demo.
- Migration ordering is looser than compose's `service_completed_successfully`
  gate: the post-provision hook runs the migrate job after provisioning;
  on image upgrades the job must be re-run manually (`az containerapp job
  start`) — documented in `deploy/azure/README.md`.
