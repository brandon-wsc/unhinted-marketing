# Getting Started

Local development setup for Unhinted Marketing Agent. For current feature status see [STATUS.md](./STATUS.md); for architecture see [ROADMAP.md](./ROADMAP.md).

---

## Prerequisites

- Python 3.11+
- Node.js 20+ (frontend)
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
npm install
npm run dev
```

Open [http://localhost:5173/login](http://localhost:5173/login). Vite proxies `/auth` → `:8000`.

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

# Background scheduler (hourly ingest, 12h questions)
python -m cmd.scheduler --once
python -m cmd.scheduler
```

Set `OPENAI_API_KEY` in `.env` for LLM-generated questions; without it, template fallbacks are used.

---

## API overview

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create account + default company |
| POST | `/auth/login` | Email/password login |
| POST | `/auth/refresh` | Rotate tokens (httpOnly cookie) |
| POST | `/auth/logout` | Revoke refresh token |
| GET | `/auth/me` | Current user (Bearer access token) |

### Signals & questions (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals/top` | Top HK market signals (auth required) |
| GET | `/companies/{id}/recommended-questions` | Cached landing questions (12h TTL) |

Full auth and session API specs: [ROADMAP.md](./ROADMAP.md).
