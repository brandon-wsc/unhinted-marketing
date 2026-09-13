# Self-hosted deployment

Two Docker Compose packages (ADR 0027), both production (`APP_ENV=production`,
`DEPLOYMENT_MODE=onprem`):

| Package | File | For |
|---------|------|-----|
| All-in-one | `docker-compose.yml` | Try it / single-box install — bundled pgvector Postgres |
| External DB | `docker-compose.external-db.yml` | Ops-managed deploy — bring your own Postgres |

Requires Docker with Compose v2.20+ (`docker compose version`).

## All-in-one (one command)

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

Your Postgres must have the pgvector extension available (migrations run
`CREATE EXTENSION IF NOT EXISTS vector`). No `AUTO_SECRETS` here — the compose
file fails fast on missing `DATABASE_URL` / `JWT_SECRET` / `BYOK_ENCRYPTION_KEY`.

`migrate` is a one-shot service that runs `alembic upgrade head` before `api`
and `scheduler` start. To run it standalone (e.g. before a rolling update):

```bash
docker compose -f docker-compose.external-db.yml run --rm migrate
```

## Images

Services carry both `image:` and `build:` — inside a repo checkout
`up -d --build` builds locally; `docker compose pull` works once images are
published. Coordinates default to `ghcr.io/brandon-wsc/unhinted-{api,web}:onprem`
and are overridable:

```bash
IMAGE_PREFIX=ghcr.io/your-ns IMAGE_TAG=v1.2.3 docker compose pull
```

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

# Upgrade in place (migrate runs again automatically on up)
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
