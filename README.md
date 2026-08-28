# Unhinted Marketing Agent

AI marketing assistant for the Hong Kong market — background signal ingestion plus user-guided content preview and publish.

## What it does

Unhinted scans HK market signals (Google Trends today; more sources planned), surfaces recommended content angles tied to your company and personas, and will guide users through chat → preview → confirm post. Publishing uses traditional platform APIs; the LLM stays in the recommendation and preview loop only.

**Today:** auth, signal ingestion, recommended-questions API, Phase 3 session UI (chat stream, agent action records, landing questions, IG Preview + Confirm stub, Gemini-style history sidebar), backend pytest (`tests/unit` + `tests/api`), and frontend Vitest (`cd web && pnpm test`) are live.

## Stack

FastAPI · PostgreSQL (pgvector) · React · LangGraph + LiteLLM (Phase 2+)

## Documentation

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Portable coding-agent entry (SSOT map + execution rules; not editor-specific) |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | Local setup, env, run commands, API overview |
| [docs/STATUS.md](docs/STATUS.md) | What's implemented today vs the roadmap |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Architecture, phases, and product plan |
| [docs/adr/](docs/adr/) | Architecture Decision Records |
| [docs/contracts/](docs/contracts/) | JSON Schema mirrors + SSE event catalog |
| [docs/openapi.json](docs/openapi.json) | Generated OpenAPI (refresh via `python -m scripts.export_contracts`) |
| [docs/TESTING.md](docs/TESTING.md) | Test tiers + path coverage gates (utils / API / UI) |
| [docs/infra/cloudflare.md](docs/infra/cloudflare.md) | Production Cloudflare (Tunnel, R2, WAF, Turnstile) |

## Quick start

```bash
cp .env.example .env   # set DATABASE_URL and secrets
pip install -e ".[dev]"
alembic upgrade head
uvicorn cmd.api.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend: `cd web && pnpm install && pnpm run dev` → [http://localhost:5173/login](http://localhost:5173/login)

Frontend tests: `cd web && pnpm test` (also `pnpm run test:coverage`, `pnpm run build`).

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for full setup (DB, workers, scheduler, tests).
