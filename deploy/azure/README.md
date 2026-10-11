# Azure Container Apps demo deploy (ADR 0044)

Hosted demo track on **Azure Container Apps (Consumption)** + **external Postgres (Neon)**, deployed with [azd](https://learn.microsoft.com/azure/developer/azure-developer-cli/). It reuses the published GHCR release images as-is (`imagePassthrough` — no build, no ACR). This is a demo/eval path; the customer install tracks stay on `deploy/docker-compose*.yml` (ADR 0027 / 0037).

```
demo.unhinted.hk ──HTTPS──▶ web (nginx :80, external ingress)
                                │ /api → http://<api>.internal.<env> (port 80 → 8000)
                                ▼
                            api (internal ingress :8000)
   scheduler + worker (no ingress, replicas=1)   migrate (Manual job → alembic)
                                │
   Neon Postgres (DATABASE_URL) · Azure Files appdata → /app/data (media)
```

Estimated cost: ~USD 35–65/mo (East Asia) — ACA consumption mostly idle + Neon free tier + ~2 GB Files. Egress under 100 GB/mo is free.

## Prerequisites

- `az` + `azd` (`brew install azure-cli azd`), logged in: `azd auth login`
- **Neon project** (free tier fine). Any managed Postgres with the `vector` extension works — migrations run `CREATE EXTENSION IF NOT EXISTS vector`.
  - Use the **direct endpoint**, not the `-pooler` host (PgBouncer transaction mode breaks asyncpg prepared statements and row-level locking).
  - The SQLAlchemy URL needs the **asyncpg** form:
    `postgresql+asyncpg://USER:PASS@ep-xxxx.ap-southeast-1.aws.neon.tech/unhinted?ssl=require`
    — Neon prints `?sslmode=require&channel_binding=require`; asyncpg does not accept `sslmode`, swap it for `ssl=require`.
- GHCR packages public (one-time repo-owner step, see `deploy/README.md`), or add registry credentials to the apps in `infra/main.bicep`.

## Deploy

```bash
azd env new unhinted-demo          # pick subscription + location (e.g. eastasia)
azd env set DATABASE_URL    'postgresql+asyncpg://...@ep-....neon.tech/unhinted?ssl=require'
azd env set JWT_SECRET      "$(openssl rand -base64 48)"
azd env set BYOK_ENCRYPTION_KEY "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
azd env set WEB_BASE_URL    'https://demo.unhinted.hk'   # planned public URL
azd up
```

`azd up` provisions `infra/` (Log Analytics, storage, ACA env, 4 container apps, migrate job) then the `postprovision` hook uploads the nginx template, restarts the web revision, and runs `alembic upgrade head`.

Optional env sets: `OPENAI_API_KEY`, `TAVILY_API_KEY`, `PUBLISH_ADAPTER` (default `stub`; `instagram` needs a Meta app), `IMAGE_TAG` (default `onprem` — pin a `v*` tag for a frozen demo), `CORS_ORIGINS` (defaults to `WEB_BASE_URL`).

First boot: open the web URL → `/setup` wizard creates SUPERADMIN + first org (ADR 0026). `WEB_BASE_URL` seeds `instance_settings` once — afterwards Platform → Instance wins, so changing the URL later is an in-app edit, not a redeploy.

## Custom domain (demo.unhinted.hk)

ACA issues a **free managed certificate**; you only pay for DNS.

1. `CNAME demo → <WEB_FQDN>` (printed at the end of `azd up`)
2. `TXT asuid.demo → <customDomainVerificationId>` (also printed)
3. `az containerapp hostname add` → `az containerapp env certificate create --validation-method CNAME` → `az containerapp hostname bind` — the hook prints all three commands ready to paste.

## Operations

```bash
# Logs (Log Analytics backed; --follow streams)
az containerapp logs show -g rg-unhinted-demo -n unhinted-demo-api --follow
az containerapp logs show -g rg-unhinted-demo -n unhinted-demo-worker --follow

# Re-run migrations after pulling a newer image tag
az containerapp job start -g rg-unhinted-demo -n unhinted-demo-migrate

# Update to a newer release tag
azd env set IMAGE_TAG v1.2.3 && azd up

# One-off admin CLI inside the api container
az containerapp exec -g rg-unhinted-demo -n unhinted-demo-api \
  --command "python -m cmd.worker signals"

azd down    # tear everything in the resource group down
```

## Notes

- **`DEPLOYMENT_MODE=onprem` stays** — this is a self-hosted install that happens to run on Azure (first-run `/setup`, local media on the shared Files volume). Cloud mode would require S3 (ADR 0023/0024); Azure Blob is not S3-compatible.
- **scheduler / worker are pinned to 1 replica** — the job queue is Postgres `FOR UPDATE SKIP LOCKED` (ADR 0039), safe to scale later but pointless for a demo.
- **Secrets** are ACA secrets (`secretRef`), not `AUTO_SECRETS` — there is no shared `appdata/.secrets.env` trick across apps.
- **nginx upstream**: the stock web image hardcodes `proxy_pass http://api:8000`. ACA internal ingress listens on port 80, so `deploy/azure/nginx/default.conf.template` is uploaded to the `nginx-conf` share and mounted at `/etc/nginx/templates` — the stock nginx entrypoint envsubsts it at container start. No rebuild.
- **Two ACA routing gotchas** (both handled in the template + bicep): internal ingress routes by **Host header** — send `Host $proxy_host`, not the public `$host` or it 404s "app does not exist"; and `allowInsecure:false` 301s HTTP→HTTPS, which `proxy_pass` won't follow — api's ingress sets `allowInsecure: true` (internal hop is plain HTTP; TLS terminates at web's external ingress).
- **Media on Azure Files** (`appdata` → `/app/data`) is shared between api and worker. Instagram Confirm still needs a public-HTTPS media URL (ADR 0043) — for real publish, set up S3-compatible storage in Settings → Storage instead.
- Session SSE streams fine through ACA ingress (no buffering); the nginx location keeps `proxy_buffering off` and a 1-hour read timeout.
