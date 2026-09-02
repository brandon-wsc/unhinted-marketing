# Getting Started

Local development setup for Unhinted Marketing Agent. For current feature status see [STATUS.md](./STATUS.md); for architecture see [ROADMAP.md](./ROADMAP.md).

---

## Prerequisites

- Python 3.11+
- Node.js 22+ and pnpm 11.20+ (frontend; enable via `corepack enable`)
- PostgreSQL with pgvector (dev DB or your own instance)

---

## Environment

```bash
cp .env.example .env
```

**Dev DB:** `192.168.5.20:5434` (database `unhinted`). Set your password in `.env`:

```
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@192.168.5.20:5434/unhinted
```

**pgvector:** install on the server; Phase 1 migrations run `CREATE EXTENSION vector` when needed.

Other variables: see `.env.example` and the [Environment](./STATUS.md#environment) section in STATUS.

---

## Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn cmd.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

---

## Frontend

```bash
cd web
pnpm install
pnpm run dev
```

Open [http://localhost:5173/login](http://localhost:5173/login). Vite proxies `/api` → `:8000`. SPA document routes (`/`, `/login`, `/admin`, …) are not proxied.

---

## Workers & scheduler

```bash
# Ingest Google Trends HK
python -m cmd.worker hot-search

# Print top signals in terminal
python -m cmd.worker signals

# Generate recommended questions (needs OPENAI_API_KEY or fallback templates)
python -m cmd.worker questions

# Promote high-rank signals → topic entities in PostgreSQL
python -m cmd.worker promote

# Full pipeline
python -m cmd.worker all

# Wipe all signal data (keeps auth, companies, personas); optional re-ingest
python -m cmd.worker reset-signals
python -m cmd.worker reset-signals --reingest

# Org Instagram token for Confirm (ADR 0022; never prints the raw token)
python -m cmd.worker connect-social-account --company UUID --ig-user-id ID --token TOKEN

# Background scheduler (hourly ingest, 12h questions)
python -m cmd.scheduler --once
python -m cmd.scheduler
```

Set `OPENAI_API_KEY` in `.env` for LLM-generated questions; without it, template fallbacks are used. Optional `LLM_API_BASE` (OpenRouter / DeepSeek / etc.): model ids are routed through the OpenAI-compatible client against that base (OpenRouter `org/model` slugs kept) — see `.env.example`.

---

## API overview

All public JSON/SSE routes are under `/api` ([ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md)).

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create account + default company |
| POST | `/api/auth/login` | Email/password login |
| POST | `/api/auth/refresh` | Rotate tokens (httpOnly cookie) |
| POST | `/api/auth/logout` | Revoke refresh token |
| GET | `/api/auth/me` | Current user (Bearer access token) |

### Signals & questions (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/signals/top` | Top HK market signals (auth required) |
| GET | `/api/companies/{id}/recommended-questions` | Cached landing questions (12h TTL) |

### Sessions (Phase 2–3)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sessions?company_id=` | History list (pinned first; title or first-message preview) |
| POST | `/api/sessions` | Create session |
| PATCH | `/api/sessions/{id}` | Rename (`title` / `clear_title`) and/or `pinned` |
| DELETE | `/api/sessions/{id}` | Delete session (+ cascaded messages/drafts) |
| POST | `/api/sessions/{id}/messages` | User turn (LangGraph); 409 if busy or parked awaiting image |
| GET | `/api/sessions/{id}/messages` | Hydrate transcript (`metadata.agent_actions` + `duration_ms` on user turns) |
| POST | `/api/sessions/{id}/resume-image` | Resume parked graph into image plan/gen ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md)) |
| POST | `/api/sessions/{id}/stop` | Discard in-flight or parked turn |
| POST | `/api/sessions/{id}/draft` | Manual draft revision (no LLM) |
| GET | `/api/sessions/{id}/events` | SSE stream (snapshot includes `interrupted` for Generate-image CTA) |
| POST | `/api/sessions/{id}/confirm` | Confirm publish (stub by default; Instagram when `PUBLISH_ADAPTER=instagram`) |
| GET | `/api/companies/{id}/social-accounts` | List org Instagram credentials (editor; `token_last4` only) |
| PUT / DELETE | `/api/companies/{id}/social-accounts/instagram` | Save or disconnect the org IG token |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness → `{"status":"ok"}` |

Full auth and session specs: [ROADMAP.md](./ROADMAP.md); what’s shipped: [STATUS.md](./STATUS.md). Agent SSOT map: [AGENTS.md](../AGENTS.md). Refresh OpenAPI / JSON Schema mirrors: `python -m scripts.export_contracts`; regenerate FE session TS mirrors: `cd scripts/typescript_gen && npm install && npm run generate`.

---

## Tests

Coverage is **path-tiered** (utils high, API mid, pages/feature UI low, LLM omitted) — see [TESTING.md](./TESTING.md).

```bash
pip install -e ".[dev]"

# Unit (no DB)
pytest tests/unit

# API integration — dedicated DB only (see TEST_DATABASE_URL in .env.example)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@HOST:PORT/unhinted_test
# create the empty database once, then:
pytest tests/api

# Path-tiered coverage examples
pytest tests/unit --cov=internal.auth.jwt --cov=schemas --cov-fail-under=85
TEST_DATABASE_URL=... pytest tests/api --cov=cmd.api.routes --cov-fail-under=70

# Frontend — Vitest (Tier 1 utils + Tier 2 shared components)
cd web
pnpm test
pnpm run test:coverage
pnpm run build
```

On-demand live agent eval (same `OPENAI_API_KEY` as session nodes; not CI). Suites, VOICE judge, `--skip-judge`: [TESTING.md](./TESTING.md).

```bash
python -m scripts.eval_agent              # suite=smoke
python -m scripts.eval_agent --suite all
# report: reports/eval/latest.md (gitignored)
```

API fixtures run `alembic upgrade head` against `TEST_DATABASE_URL` and truncate tables between tests. Do **not** point `TEST_DATABASE_URL` at your main `unhinted` dev database if you care about its data.

Frontend component tests mock i18n / auth / theme; see [TESTING.md](./TESTING.md).
