# Unhinted Marketing Agent

AI marketing assistant for the Hong Kong market — background signal ingestion plus user-guided content preview and publish. The LLM owns the recommend/draft loop only; publishing is a traditional Confirm → HTTP flow.

## Self-host (Docker)

**All-in-one** — bundled pgvector Postgres, single box:

```bash
curl -LO https://github.com/brandon-wsc/unhinted-marketing/releases/latest/download/compose.yaml
docker compose -f compose.yaml up -d   # → http://localhost:8484, first-run /setup wizard
```

**External DB** — bring your own Postgres (pgvector required):

```bash
curl -LO https://github.com/brandon-wsc/unhinted-marketing/releases/latest/download/compose.external-db.yaml
curl -LO https://github.com/brandon-wsc/unhinted-marketing/releases/latest/download/env.example
cp env.example .env   # DATABASE_URL, JWT_SECRET, BYOK_ENCRYPTION_KEY, WEB_BASE_URL, CORS_ORIGINS
docker compose -f compose.external-db.yaml up -d
```

From a checkout instead: `cd deploy && docker compose up -d` — pulls prebuilt
images; add `--build` to build from source. [Full ops guide](deploy/README.md).

## Develop

```bash
cp .env.example .env   # set DATABASE_URL and secrets
pip install -e ".[dev]"
alembic upgrade head
uvicorn cmd.api.main:app --reload
```

Frontend: `cd web && pnpm install && pnpm run dev` → [unhinted.localhost:5173/login](https://unhinted.localhost:5173/login) · tests `pnpm test`

Stack: FastAPI · PostgreSQL (pgvector) · React · LangGraph + LiteLLM

## Docs

[Getting started](docs/GETTING_STARTED.md) · [Roadmap](docs/ROADMAP.md) · [ADRs](docs/adr/) · [Deploy guide](deploy/README.md) · [Agent notes](AGENTS.md)

## License

[MIT](LICENSE) © 2026 brandon-wsc
