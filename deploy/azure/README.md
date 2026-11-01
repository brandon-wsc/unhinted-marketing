# Azure Container Apps demo deploy (ADR 0044)

Hosted demo track on **Azure Container Apps (Consumption)** + **external Postgres (Neon)**, deployed with [azd](https://learn.microsoft.com/azure/developer/azure-developer-cli/). It reuses the published GHCR release images as-is (`imagePassthrough` — no build, no ACR). This is a demo/eval path; the customer install tracks stay on `deploy/docker-compose*.yml` (ADR 0027 / 0037).

```
demo.unhinted.hk ──HTTPS──▶ web (nginx :80, external ingress)
                                │ /api → http://<api>.internal.<env> (port 80 → 8000)
                                ▼
                            api (internal ingress :8000)
   worker (internal ingress /kick only; scales 0→1 on enqueue kicks — ADR 0058)
   scheduler (scheduled Job, cron */15m → cmd.scheduler --once)
   migrate (Manual job → alembic)
                                │
   Neon Postgres (DATABASE_URL) · Azure Files appdata → /app/data (media)
```

Estimated cost: ~USD 10–20/mo (East Asia) — web/api scale to zero on ingress, the worker scales to zero via kick-activated ingress (ADR 0058), the scheduler runs only on its cron tick. Neon free tier + ~2 GB Files + Log Analytics ingestion are the rest. Egress under 100 GB/mo is free.

> **Why not bare `minReplicas: 0`?** ACA only honors scale-to-zero on apps it can scale — ingress traffic or an explicit KEDA rule. A no-ingress app with `minReplicas: 0` and no rules just stays up. The Oct 2026 bill (~$3.3/day ≈ $99/mo run rate) was almost entirely the worker + scheduler running 24/7. The worker now has internal ingress on `/kick` so enqueue commits wake it (ADR 0058 §9); the scheduler became a scheduled Job. A KEDA `postgresql` scaler was deliberately *not* used — its ~30s query cadence would keep the scale-to-zero Neon compute awake (ADR 0058 §4/Alternatives).

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

ACA issues a **free managed certificate**; you only pay for DNS. The binding is
declarative in `infra/main.bicep` (`ingress.customDomains` + a managed cert on
the env), so `azd up` / `azd provision` re-asserts it instead of wiping it —
a manually-bound hostname gets silently dropped by every provision PUT.

1. `CNAME demo → <WEB_FQDN>` (printed at the end of `azd up`)
2. `TXT asuid.demo → <customDomainVerificationId>` (also printed)
3. `azd env set CUSTOM_DOMAIN_NAME demo.unhinted.hk && azd up` — provision creates
   the managed cert (`cert-demo-unhinted-hk`) and binds it `SniEnabled`.
   To adopt an existing az-generated cert instead of minting a second one:
   `azd env set CUSTOM_DOMAIN_CERT_NAME mc-…`.

DNS must be live **before** provisioning — cert issuance does a CNAME lookup.

## Operations

```bash
# Logs (Log Analytics backed; --follow streams)
az containerapp logs show -g rg-unhinted-demo -n unhinted-demo-api --follow
az containerapp logs show -g rg-unhinted-demo -n unhinted-demo-worker --follow

# Re-run migrations after pulling a newer image tag
az containerapp job start -g rg-unhinted-demo -n unhinted-demo-migrate

# Force a scheduler tick now instead of waiting for the cron
az containerapp job start -g rg-unhinted-demo -n unhinted-demo-scheduler
az containerapp job execution list -g rg-unhinted-demo -n unhinted-demo-scheduler -o table

# Update to a newer release tag
azd env set IMAGE_TAG v1.2.3 && azd up

# One-off admin CLI inside the api container
az containerapp exec -g rg-unhinted-demo -n unhinted-demo-api \
  --command "python -m cmd.worker signals"

azd down    # tear everything in the resource group down
```

## Notes

- **`DEPLOYMENT_MODE=onprem` stays** — this is a self-hosted install that happens to run on Azure (first-run `/setup`, local media on the shared Files volume). Cloud mode would require S3 (ADR 0023/0024); Azure Blob is not S3-compatible.
- **worker wake + drain semantics** — an enqueue commit posts a fire-and-forget `POST /kick` to the worker's internal ingress; cold start + FastEmbed warmup means the first claim after idle lands ~1–3 min late. An idle replica scales to 0 on the HTTP-scaler cooldown; a mid-drain scale-down sends SIGTERM and `terminationGracePeriodSeconds: 600` lets the in-flight job finish — anything longer stays `running` until the next replica's 15-min reclaim sweep returns it to `pending`. Deferred jobs (retry backoff, questions jitter) due while the worker sleeps stall to the next enqueue kick (hourly hot tick or user action).
- **settings edits** — `SCHEDULER_KICK_URL` has no listener now, so Platform scheduler interval edits apply on the next cron tick (≤15 min), not ADR 0050's ~1 min.
- **worker is a singleton** — `maxReplicas: 1`; the queue is Postgres `FOR UPDATE SKIP LOCKED` (ADR 0039), safe to raise later but pointless for a demo.
- **kick activator spike (ADR 0058 §9)** — unverified whether ACA still boots a replica when the kicking client abandons on its 10 s timeout (cold start can exceed it). Watch for a stalled queue on the first demo run; if kicks don't activate, fall back is `worker minReplicas: 1` or raising the kick timeout in `internal/memory/wake.py`.
- **Secrets** are ACA secrets (`secretRef`), not `AUTO_SECRETS` — there is no shared `appdata/.secrets.env` trick across apps.
- **nginx upstream**: the stock web image hardcodes `proxy_pass http://api:8000`. ACA internal ingress listens on port 80, so `deploy/azure/nginx/default.conf.template` is uploaded to the `nginx-conf` share and mounted at `/etc/nginx/templates` — the stock nginx entrypoint envsubsts it at container start. No rebuild.
- **Two ACA routing gotchas** (both handled in the template + bicep): internal ingress routes by **Host header** — send `Host $proxy_host`, not the public `$host` or it 404s "app does not exist"; and `allowInsecure:false` 301s HTTP→HTTPS, which `proxy_pass` won't follow — api's ingress sets `allowInsecure: true` (internal hop is plain HTTP; TLS terminates at web's external ingress).
- **Media on Azure Files** (`appdata` → `/app/data`) is shared between api and worker. Instagram Confirm still needs a public-HTTPS media URL (ADR 0043) — for real publish, set up S3-compatible storage in Settings → Storage instead.
- Session SSE streams fine through ACA ingress (no buffering); the nginx location keeps `proxy_buffering off` and a 1-hour read timeout.
