# Unhinted Marketing Agent

AI marketing assistant for the Hong Kong market — background signal ingestion plus user-guided content preview and publish.

## What it does

Unhinted scans HK market signals (Google Trends today; more sources planned), surfaces recommended content angles tied to your company and personas, and will guide users through chat → preview → confirm post. Publishing uses traditional platform APIs; the LLM stays in the recommendation and preview loop only.

**Today:** auth, signal ingestion, recommended-questions API, and Phase 3 session UI (chat stream, agent action records, landing questions, IG Preview + Confirm stub, Gemini-style history sidebar) are live.

## Stack

FastAPI · PostgreSQL (pgvector) · React · LangGraph + LiteLLM (Phase 2+)

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | Local setup, env, run commands, API overview |
| [docs/STATUS.md](docs/STATUS.md) | What's implemented today vs the roadmap |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Architecture, phases, and product plan |

## Quick start

```bash
cp .env.example .env   # set DATABASE_URL and secrets
pip install -e ".[dev]"
alembic upgrade head
uvicorn cmd.api.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend: `cd web && npm install && npm run dev` → [http://localhost:5173/login](http://localhost:5173/login)

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for full setup (DB, workers, scheduler).
