# Self-hosted deployment

Two Docker Compose packages (ADR 0027), both production (`APP_ENV=production`,
`DEPLOYMENT_MODE=onprem`):

| Package | File | For |
|---------|------|-----|
| All-in-one | `docker-compose.yml` | Try it / single-box install — bundled pgvector Postgres |
| External DB | `docker-compose.external-db.yml` | Ops-managed deploy — bring your own Postgres |

Requires Docker with Compose v2.20+ (`docker compose version`).

## Two update tracks

Same compose shape, different source of truth ([ADR 0038](../docs/adr/0038-demo-local-cd.md)).

| Track | Who | What runs | How it updates |
|-------|-----|-----------|----------------|
| **Demo / local CD** | Personal machine or private demo host | Current `main` HEAD, built on that machine | `./demo-sync.sh` (git fast-forward + `docker compose up -d --build`) |
| **Customer pull CD** | Versioned self-hosted install | A published GitHub Release (GHCR version tag; floating `onprem` moves only when a release is published) | Release compose assets, or `docker compose pull` |

`demo-sync.sh` does not download Release assets and does not pull the floating
`onprem` tag. There is no `deploy/update.sh` on this track. A customer updater
must not check out `main` — running the demo script against a versioned
install rebuilds unpublished source over that install's images.

### Demo / local CD

Use a **dedicated clone** (a cron job on a working tree you also edit will
stop at the first dirty tracked file). `deploy/.env` is gitignored and is
kept across updates.

```bash
git clone https://github.com/brandon-wsc/unhinted-marketing.git /opt/unhinted
cd /opt/unhinted
cp deploy/.env.example deploy/.env   # optional; all-in-one boots without it
./deploy/demo-sync.sh                 # → http://localhost:8484
```

External DB (required secrets already in `deploy/.env`):

```bash
./deploy/demo-sync.sh -f docker-compose.external-db.yml
```

The script is the one-liner `git fetch origin main && git checkout main &&
git merge --ff-only origin/main && cd deploy && docker compose up -d --build`.
It builds `DEPLOYMENT_MODE=onprem` / `VITE_DEPLOYMENT_MODE=onprem` from that
commit (SPA + API + migrate). A cron entry on the dedicated clone:

```bash
*/30 * * * * /opt/unhinted/deploy/demo-sync.sh >>/var/log/unhinted-demo-sync.log 2>&1
```

**Env.** All-in-one defaults `WEB_BASE_URL` and `CORS_ORIGINS` to
`http://localhost:8484`. Set both in `deploy/.env` when the browser origin is
anything else (another port, a LAN host, a public name). Those values seed
`instance_settings` on first boot only — afterwards edit System → Instance
(ADR 0026). A tunnel is only for Meta: Instagram Login and real publish need
a public HTTPS origin Meta can call. A localhost demo does not need one.

### Customer pull CD

Leave this track on a Release. The curl installs below, and `docker compose
pull` of `IMAGE_TAG=onprem` or a `v*` tag, are this track. They are not
`main` HEAD.

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

That builds the commit already checked out. A demo host that should follow
`origin/main` uses `./demo-sync.sh` instead.

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

Inside a repo checkout `up -d --build` builds **this commit** locally
(demo / local CD uses `./demo-sync.sh` so that commit is `origin/main`).
`docker compose pull` fetches the latest **published release** (the floating
`onprem` tag) — customer pull CD, not `main`.
Coordinates are overridable:

```bash
IMAGE_PREFIX=ghcr.io/your-ns IMAGE_TAG=v1.2.3 docker compose pull
```

Anonymous pull needs the GHCR packages set to public — a one-time repo-owner
step (package → Settings → Change visibility) after the first publish.

`DEPLOYMENT_MODE` is baked at image build time (ADR 0023) — on-prem is the
default and correct for both packages.

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

# Rebuild the commit already checked out (migrate runs again on up).
# To move a demo host to latest main, use ./demo-sync.sh — not compose pull.
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
