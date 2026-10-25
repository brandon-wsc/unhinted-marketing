# Unhinted

Unhinted is an open-source AI social content assistant for Hong Kong businesses: it turns Hong Kong trending topics plus your product selling points into Cantonese, Instagram-style posts in your brand voice, and nothing is published until a human confirms.

[**unhinted.hk**](https://unhinted.hk) · [**Live Demo**](https://demo.unhinted.hk) (account approval required) · [**Docs**](docs/GETTING_STARTED.md)

> **你有生意要忙，唔使日日由零諗出咩。**  
> Unhinted 幫你由香港熱話搵切入點，結合產品賣點，寫成有你品牌語氣嘅社交內容。你揀方向、改稿，確認先發佈。

The LLM owns the recommend/draft loop only; publishing is a traditional Confirm → HTTP flow. Unhinted is in public beta (pre-release `v1.0.0-beta.*` builds).

![Unhinted Workspace](docs/images/workspace-preview.png)

## Why Unhinted?

- **HK-Native Voice**: Local Cantonese phrasing tailored to your brand tone — from corporate safe to sarcastic (港式抽水).
- **Trend-to-Post Ingestion**: Matches Hong Kong market signals (Google Trends HK, RSS news, web search) with your catalog.
- **Confirm ≠ Chat ([ADR 0003](docs/adr/0003-confirm-without-llm.md))**: Zero risk of AI hallucinations publishing directly. Saying "可以出" in chat will never publish; only an explicit user click on the Confirm button triggers the HTTP publish endpoint.
- **Self-Hosted & Private**: Single-command Docker deployment with PostgreSQL (pgvector). Your product catalog, brand settings, and credentials stay in your own infrastructure.

## Unhinted vs. a generic chatbot for HK Instagram

A general-purpose chatbot can write a caption from a prompt. Unhinted is built around the specific workflow of an HK brand posting to Instagram:

- **Starts from Hong Kong signals** — background workers ingest Google Trends HK and RSS news into PostgreSQL, and chat research can add web search results, so drafts begin from what Hong Kong is talking about rather than a blank prompt.
- **Grounded in your brand** — each company keeps its own brand voice settings and product catalog (pgvector retrieval), and drafts are written against both.
- **Angle before draft** — the session pauses on a set of editorial angles for you to pick before any copy is written ([ADR 0028](docs/adr/0028-angle-pick-before-draft.md)).
- **Instagram-layout preview** — drafts render in a phone-style Instagram feed mock with caption, hashtags, CTA, and images you can edit before publishing.
- **Confirm-before-publish, self-hosted** — publishing only happens through an explicit Confirm button and an HTTP endpoint, never from chat ([ADR 0003](docs/adr/0003-confirm-without-llm.md)), on infrastructure you run yourself.

## How it works

1. **Signal Ingestion**: Monitors Hong Kong market trends and pairs relevant talking points with your products.
2. **Angle Picking**: Presents multiple editorial directions before drafting — you stay in control of the angle.
3. **Interactive Workspace**: Co-pilot copywriting and visual plans with real-time Instagram layout preview.
4. **Human-in-the-Loop Confirmation**: Posts are only published when you review and click Confirm.

## Self-host (Docker)

Two Compose packages — [full ops guide](deploy/README.md):

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

From a checkout instead: `cd deploy && docker compose up -d --build` (external DB: `-f docker-compose.external-db.yml`). That builds whatever commit is checked out.

**Demo / local CD** — a personal machine or private demo host that should always run latest `main`, still the on-prem compose package: [`./deploy/demo-sync.sh`](deploy/demo-sync.sh). Customer installs stay on a GitHub Release; do not use the demo script to update those.

## Connect an AI app (MCP)

Each install is its own remote MCP server + OAuth 2.1 authorization server ([ADR 0051](docs/adr/0051-remote-mcp-server.md)). Users paste **one URL** into their AI app — `{WEB_BASE_URL}/api/mcp`, shown on the **Account** page — and the app discovers OAuth itself via `/.well-known/oauth-*` (already proxied in the shipped nginx configs). During consent the user signs in and binds the connection to **exactly one company**; drafts created by the app appear in the user's chat history with a source badge, and publishing always stays behind the in-app Confirm button.

- **Designed for:** Claude (Connectors → Custom → Web) and ChatGPT (Plugins → Add custom MCP server) — both advertise Client ID Metadata Documents, the supported registration path. Per ADR 0051 §2, each named app still needs a hands-on connect test before claiming verified support.
- **Gemini:** not supported — its connected-apps flow requires Dynamic Client Registration (RFC 7591), which we don't ship.
- **Operator requirement:** the MCP URL must be a public HTTPS endpoint reachable from the vendor's cloud (they call the server, not the user's machine). On-prem installs behind a firewall need that host exposed. `WEB_BASE_URL` must match it — consent links and token audiences are derived from it.
- **Revocation:** users manage connected apps under **Account → Connected apps**; revocation cuts the next MCP call immediately.

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
