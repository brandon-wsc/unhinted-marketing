# Self-hosted deployment

Two Docker Compose packages (ADR 0027), both production (`APP_ENV=production`,
`DEPLOYMENT_MODE=onprem`):

| Package | File | For |
|---------|------|-----|
| All-in-one | `docker-compose.yml` | Try it / single-box install — bundled pgvector Postgres |
| External DB | `docker-compose.external-db.yml` | Ops-managed deploy — bring your own Postgres |

Requires Docker with Compose v2.20+ (`docker compose version`).

## All-in-one (one command)

Standalone install (prebuilt images, no repo checkout):

```bash
curl -LO https://github.com/brandon-wsc/unhinted-marketing/releases/latest/download/compose.yaml
docker compose -f compose.yaml up -d
```

Or from a repo checkout:

```bash
cd deploy
docker compose up -d --build
```

Open http://localhost:8484 — the first-run `/setup` wizard creates the
SUPERADMIN account and first org (ADR 0026). LLM keys are skippable there and
can be added later per-org.

What happens on `up`: `db` (pgvector/pgvector:pg18) starts → `migrate` runs
`alembic upgrade head` and generates `JWT_SECRET` / `BYOK_ENCRYPTION_KEY`
(persisted to the `appdata` volume) → `api` + `scheduler` start → `web` (nginx)
serves the SPA and proxies `/api`.

Optional overrides via `.env` (`cp .env.example .env`): `WEB_PORT` /
`WEB_BIND`, `WEB_BASE_URL`, `OPENAI_API_KEY`, `POSTGRES_*` — see
[.env.example](./.env.example). The bundled database publishes no host port.

Port already allocated? Set `WEB_PORT` in `.env` and update `WEB_BASE_URL` /
`CORS_ORIGINS` to match — invite links and media URLs derive from the base
URL. `WEB_BIND=127.0.0.1` keeps a trial install off the LAN.

## External DB (ops-managed)

```bash
cd deploy
cp .env.example .env   # set DATABASE_URL, JWT_SECRET, BYOK_ENCRYPTION_KEY,
                       # WEB_BASE_URL, CORS_ORIGINS
docker compose -f docker-compose.external-db.yml up -d --build
```

Standalone: grab `compose.external-db.yaml` + `env.example` from the latest
release instead of the checkout files.

Your Postgres must have the pgvector extension available (migrations run
`CREATE EXTENSION IF NOT EXISTS vector`). No `AUTO_SECRETS` here — the compose
file fails fast on missing `DATABASE_URL` / `JWT_SECRET` / `BYOK_ENCRYPTION_KEY`.

`migrate` is a one-shot service that runs `alembic upgrade head` before `api`
and `scheduler` start. To run it standalone (e.g. before a rolling update):

```bash
docker compose -f docker-compose.external-db.yml run --rm migrate
```

## Images

Each `v*` tag runs `.github/workflows/release.yml`: it builds + pushes
`ghcr.io/brandon-wsc/unhinted-{api,web}` (multi-arch: amd64 + arm64 via QEMU)
tagged with the version **and** the
floating `onprem` tag, then attaches standalone compose assets
(`compose.yaml`, `compose.external-db.yaml`, `env.example`) to the GitHub
Release. The standalone files are derived from the `deploy/` compose files —
`build:` sections stripped, `IMAGE_TAG` default pinned to the release version.

Inside a repo checkout `up -d --build` still builds locally;
`docker compose pull` fetches the latest release (the `onprem` tag).
Coordinates are overridable:

```bash
IMAGE_PREFIX=ghcr.io/your-ns IMAGE_TAG=v1.2.3 docker compose pull
```

Anonymous pull needs the GHCR packages set to public — a one-time repo-owner
step (package → Settings → Change visibility) after the first publish.

`DEPLOYMENT_MODE` is baked at image build time (ADR 0023) — on-prem is the
default and correct for both packages.

## Public exposure via Cloudflare Tunnel (ADR 0037)

Recommended way to put an install on the internet: a remotely-managed
Cloudflare Tunnel. `cloudflared` dials **out** — no port-forwarding, no
inbound firewall rules, the host IP is never published, edge TLS is free.
Public HTTPS is also required for Meta OAuth / Live mode (the relay fans
callbacks back to the instance server-to-server — ADR 0032/0033).

1. Zero Trust → Networks → Tunnels → create a tunnel → add a public
   hostname (e.g. `marketing.example.com`) with service `http://web:80`.
2. Copy the tunnel token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
3. Set `WEB_BASE_URL` / `CORS_ORIGINS` to the public `https://` origin and
   `WEB_BIND=127.0.0.1` so the web port stays off the LAN.
4. Start with the override:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d
   ```

Only `web` is exposed — `db` publishes no host port and no other service has
a tunnel ingress. Note: Meta platform callbacks reach the instance
server-to-server via the relay, so don't blanket-gate the hostname with
Cloudflare Access (or bypass `/api/social/meta/*` + `/api/social/oauth/*`).
Rely on the app's own auth plus edge WAF/rate-limiting instead.

## Pull-based updates (ADR 0037)

`update.sh` is the install-side half of CD. Run it on the Docker host under
cron or Synology Task Scheduler — it polls GitHub Releases and, on a newer
tag: dumps the bundled `db` to `backups/`, pins `IMAGE_TAG` in `.env`,
`compose pull && up -d` (migrate re-runs alembic), then waits for `/api`
healthy. No self-hosted runner, no inbound channel from GitHub.

```bash
./update.sh           # update to the latest release tag
./update.sh --check   # print current vs latest, change nothing
TARGET_TAG=v1.2.3 ./update.sh   # pin a specific tag — also the rollback path
```

`COMPOSE_FILES` selects the stack shape (env or `.env`), e.g.
`COMPOSE_FILES="docker-compose.yml docker-compose.tunnel.yml"` or
`docker-compose.external-db.yml`. Standalone installs auto-detect
`compose.yaml`.

**Synology:** copy the release assets (`compose.yaml`, `compose.tunnel.yaml`,
`env.example` → `.env`, `update.sh`) into e.g. `/volume1/docker/unhinted`,
`chmod +x update.sh`, start via Container Manager project or
`docker compose -f compose.yaml -f compose.tunnel.yaml up -d` over SSH, then
schedule `cd /volume1/docker/unhinted && ./update.sh` in Task Scheduler
(e.g. every 30 min). Output appends to `update.log`; dumps land in
`backups/`.

## Operations

```bash
# Logs / status
docker compose logs -f api
docker compose ps

# Admin CLI (worker subcommands run inside the api container)
docker compose exec api python -m cmd.worker signals
docker compose exec api python -m cmd.worker set-platform-role --email you@x.com --level superadmin
docker compose exec api python -m cmd.worker reset-signals --reingest

# All-in-one only: AUTO_SECRETS lives in the entrypoint's process env — `exec`
# spawns a new process that does NOT inherit it. Commands that encrypt/decrypt
# org keys or tokens must source the persisted file first:
docker compose exec api sh -c 'set -a; . /app/data/.secrets.env; set +a; \
  python -m cmd.worker connect-social-account --company UUID --ig-user-id ID --token TOKEN'

# Upgrade in place (migrate runs again automatically on up) — or let
# update.sh poll + apply releases with a pre-upgrade db dump
docker compose up -d --build
```

## Volumes & backup

| Volume | Contents |
|--------|----------|
| `pgdata` | Bundled Postgres data (all-in-one only) |
| `appdata` | `media/` uploaded + generated media; `.secrets.env` auto-generated JWT/BYOK keys (all-in-one) |

Back up both volumes for a full snapshot. **Warning:** deleting `appdata` on
the all-in-one package rotates JWT_SECRET and BYOK_ENCRYPTION_KEY — sessions
log out and stored org BYOK keys become undecryptable (same blast radius as
losing `BYOK_ENCRYPTION_KEY`, ADR 0020).

## Notes

- **HTTPS / Instagram OAuth** — real publish (`PUBLISH_ADAPTER=instagram`) and
  Instagram Login need a public HTTPS `WEB_BASE_URL` plus `META_*` env; default
  `stub` adapter never calls Meta (ADR 0022).
- **Media** — local disk under `appdata` by default (ADR 0024); optional S3
  env seeds the first `storage_configs` row, then System → Storage in the app
  is the source of truth (ADR 0025).
- The root `docker-compose.yml` is the dev database only (db + adminer) — it is
  unrelated to these deployment packages.
