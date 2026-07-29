# Unhinted Marketing — Project Status

> **Last updated:** 2026-07-29  
> **Overall:** Phase 0–1 complete · Phase 2 **soft-complete** (UI-ready) · Phase 3 UI **in progress** (chat shell + token stream done)  
> **Dev DB:** `192.168.5.20:5434` / database `unhinted`

This document summarizes **what exists today** vs the [ROADMAP](./ROADMAP.md). For architecture and phase plans, see ROADMAP.

---

## Summary

| Area | Status |
|------|--------|
| Auth backend (JWT, register/login) | ✅ Done |
| Auth DB tables + Alembic | ✅ Done |
| React login / register / dashboard shell | ✅ Done |
| i18n (zh-HK, English JSON keys) | ✅ Done |
| Dark / light / system theme | ✅ Done |
| App header (logo + settings dropdown) | ✅ Done |
| HK hot search ingestion | ✅ Done (Google Trends HK only) |
| Recommended questions cache + API | ✅ Done |
| OKF knowledge scaffold | ➖ Removed — knowledge in PostgreSQL only |
| LangGraph session / preview / confirm API | ✅ Soft-complete — enough for Phase 3 UI |
| Chat UI shell (`useSession` + Streamdown) | ✅ Done |
| Chat token stream (`message.delta`) | ✅ Done — live deltas via SSE, batched in node |
| pgvector on dev DB | ✅ Done (PG 18.4 · `pgvector/pgvector:pg18`; enable with `CREATE EXTENSION vector`) |

**Current user-facing flow:** Register or login → `/` is the chat workspace — send a message, assistant replies stream token-by-token (chat intent) or run the Agent path (brief/draft events, cards UI still pending). Preview/Confirm UI next.

**Decision (2026-07-29):** Remaining Phase 2 items are **held**; start Phase 3 product UI against the existing session APIs.

**Decision (2026-07-29) — Phase 3 UI build order + UX:**

1. Chat UI shell (REST + existing SSE, full messages)
2. Chat token stream (`message.delta` on `chat` node only; Streamdown for streaming MD)
3. Agent Mode UI (`agent.progress` status line + brief/interrupt cards — do **not** stream Agent JSON as chat MD)
4. Landing recommended-question cards
5. Preview (left chat / right draft) + Confirm button

BYOK / Trace / Meta stay deferred. No full Vercel AI SDK `useChat` — thin `useSession` + custom SSE; markdown via standalone [`streamdown`](https://streamdown.ai/) + `@streamdown/cjk`.

---

## Phase Progress

### Phase 0 — Project Bootstrap · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Git repo | ✅ | |
| `docs/ROADMAP.md` | ✅ | |
| `docs/STATUS.md` | ✅ | This file |
| `.env.example` | ✅ | Includes LLM keys / `LLM_API_BASE` |
| `pyproject.toml` + Python skeleton | ✅ | FastAPI, SQLAlchemy, Alembic, JWT, LangGraph |
| Auth API | ✅ | `/auth/register`, `/login`, `/refresh`, `/logout`, `/me` |
| Alembic `8791b607d5bc` (auth) | ✅ | `users`, `entities`, `organization_members`, `refresh_tokens` |
| React web app | ✅ | Vite + React 19 + Tailwind v4 |
| README | ✅ | Project intro; setup in GETTING_STARTED |
| `docker-compose.yml` | ➖ | Removed — dev DB is external |
| Auth rate limiting | ⬜ | Planned (Redis or in-memory) |
| Automated tests | ⬜ | No `tests/` yet |

### Phase 1 — Data & Autopilot Backend · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Alembic `5dae474953cd` (signals) | ✅ | `raw_news_events`, `edges`, `recommended_questions` |
| Hot search worker | ✅ | `python -m cmd.worker hot-search` (Google Trends HK) |
| Question generator | ✅ | LiteLLM + 12h cache; template fallback without API key |
| News promoter | ✅ | Top trends → topic `entities` + `edges` in PG |
| LiteLLM BYOK loader | ✅ | Env-based (`OPENAI_API_KEY`, model tiers) |
| Default personas | ✅ | Seeded in `entities` (type=persona) on first question run |
| Signals API | ✅ | `GET /signals/top` |
| Questions API | ✅ | `GET /companies/{id}/recommended-questions` |
| Scheduler | ✅ | `python -m cmd.scheduler` |
| CLI signals | ✅ | `python -m cmd.worker signals` |

### Phase 2 — LangGraph Session + API · **soft-complete (~65%)**

Backend session loop is **UI-ready**. Graph contract locked in [ROADMAP.md](./ROADMAP.md). Remaining checklist items are **explicitly held** so product UI can ship first.

| Item | Status | Notes |
|------|--------|-------|
| ROADMAP graph contract | ✅ | 12 nodes + `persist_preview`; edges + interrupt |
| Migrations | ✅ | Alembic `526ca8643303` — `sessions`, `session_messages`, `preview_drafts`, `tool_receipts` |
| LangGraph graph + interrupt | ✅ | `interrupt_before=executor_image_plan`; resume via `POST /messages` |
| Postgres checkpointer | ✅ | `AsyncPostgresSaver` + pool; `setup()` on API lifespan; `thread_id = session.id` |
| Node logic | ✅ | LiteLLM + structured I/O; heuristic fallbacks; PG load/grounding |
| Session HTTP API | ✅ | `POST /sessions`, `/messages`, `/confirm` |
| SSE `/events` | ✅ | Snapshot + live fan-out + heartbeat (in-process bus; single worker) |
| Image generation worker | ⏸ **Held** | Still `placeholder://` URL — fine for UI mock preview |
| `query_market_trends` tool schema | ⏸ **Held** | Signals already served; schema polish deferred |
| Curl exit-criteria script | ⏸ **Held** | Manual/API path works; formal curl checklist later |

**Held Phase 2 work does not block Phase 3 UI.**

### Phase 3 — React Dashboard + Meta Signals · **~35% · IN PROGRESS**

**Focus now:** Preview Mode + Confirm (see build order above). Meta ingest / BYOK / Trace after core preview → confirm.

| Item | Status | Notes |
|------|--------|-------|
| Auth pages + protected shell | ✅ | Login / register; `/` is now the chat workspace |
| Chat UI shell | ✅ | `web/src/features/session/` — `useSession` + message list / composer; Streamdown + `@streamdown/cjk`; Vite proxy covers `/sessions` `/companies` `/signals` |
| Chat token stream (`message.delta`) | ✅ | `chat` node streams LiteLLM → batched live deltas via event bus; first message waits for SSE open before POST |
| Agent Mode UI | ✅ | `agent.progress` published live inside each graph node (decorator in `nodes.py`); status line w/ model tier/id + brief card + interrupt card (click resumes image gen via `POST /messages`) |
| Landing: recommended questions cards | ✅ | Empty-state cards from `GET /companies/{id}/recommended-questions`; click → `sendMessage` (start intent); soft-fail on 404 / network |
| Preview Mode (left chat / right preview) | ⬜ | **Next** — Consume SSE `preview.updated` + draft state |
| Confirm button → `/confirm` | ⬜ | Show receipt status |
| Meta Graph API hot search | ⏸ | Can wait until after core UI |
| BYOK settings page | ⏸ | After core UI |
| Trace viewer | ⏸ | After core UI |

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/auth`)
- **Signals:** `GET /signals/top` — latest HK market signals from PostgreSQL
- **Questions:** `GET /companies/{id}/recommended-questions` — cached 12h question batch
- **Sessions:** `POST /sessions`, `POST /sessions/{id}/messages`, `GET /sessions/{id}/events` (SSE: snapshot + live push), `POST /sessions/{id}/confirm` (receipt stub)
- **LangGraph:** Session nodes + Postgres checkpointer; image URL still placeholder
- **Security:** Argon2 password hashing, refresh token rotation + revoke on logout
- **Multi-tenant bootstrap:** Register auto-creates `entities` (type `company`) + `organization_members` (role `owner`)

**Run:**

```bash
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn cmd.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Workers (`cmd/worker`, `cmd/scheduler`)

```bash
python -m cmd.worker hot-search    # Google Trends HK → PG
python -m cmd.worker signals       # CLI: print top HK signals
python -m cmd.worker questions     # Generate cached questions per company
python -m cmd.worker promote       # Promote signals → topic entities in PG
python -m cmd.worker all           # Full pipeline
python -m cmd.worker reset-signals              # Wipe signal data (destructive)
python -m cmd.worker reset-signals --reingest   # Wipe + hot-search → promote → questions
python -m cmd.scheduler --once     # One scheduler cycle
```

Set `OPENAI_API_KEY` (and optional `LLM_API_BASE`) in `.env` for LLM paths; without keys, session/question code uses heuristic/template fallbacks.

### Database (dev)

| Table | Purpose |
|-------|---------|
| `users` | Accounts |
| `entities` | Companies (and future entity types) |
| `organization_members` | User ↔ company RBAC |
| `refresh_tokens` | Hashed refresh token families |
| `raw_news_events` | Ingested HK signals (Google Trends HK; Meta API later in Phase 3) |
| `edges` | Graph links (signal → topic entities) |
| `recommended_questions` | 12h cached landing question JSON |
| `sessions` | Chat session (mode, user_id, company_id, state JSONB) |
| `session_messages` | Chat log |
| `preview_drafts` | Revision chain + approval_token |
| `tool_receipts` | Idempotent Confirm / tool receipts |
| LangGraph checkpoint tables | Owned by `AsyncPostgresSaver.setup()` (not Alembic) |

**pgvector:** Dev DB on Synology NAS runs **`pgvector/pgvector:pg18`** (PostgreSQL **18.4**). PG 18+ Docker images mount data at **`/var/lib/postgresql`** (not `/var/lib/postgresql/data`). After restore/migrate, run `CREATE EXTENSION vector;` on `unhinted`.

### Frontend (`web/`)

| Route | Description |
|-------|-------------|
| `/login` | Email/password login |
| `/register` | Sign up + default workspace |
| `/` | Protected **chat workspace** — message list + composer, streaming assistant replies |

**UX features:**

- **Header:** Logo + brand name (top-left); user menu dropdown (top-right) with language, theme, logout
- **i18n:** `react-i18next`, locale `zh-HK`, keys in English in `web/src/i18n/locales/zh-HK.json` — extensible via `SUPPORTED_LOCALES`
- **Theme:** Light / dark / system, persisted in `localStorage`
- **Form memory:** Last user email / display name / org name from `localStorage` (not fake placeholders)
- **Auth:** Access token in memory; refresh via cookie; auto-refresh on app load
- **Phase 3 (shipped):** Chat workspace at `/` — `useSession` REST-first + SSE enhancement; Streamdown (`mode="streaming"` + `@streamdown/cjk`) assistant MD; SSE `message.delta` live tokens; Agent Mode UI: live `agent.progress` status line + brief / `draft.awaiting_image_ok` interrupt cards; no `useChat`
- **Session client:** `web/src/features/session/` — `api.ts` (REST), `sse.ts` (`@microsoft/fetch-event-source` with Bearer), `use-session.ts`, `components/chat-panel.tsx`

**Run:**

```bash
cd web && npm install && npm run dev
```

App: http://localhost:5173/login (Vite proxies `/auth`, `/sessions`, `/signals`, `/companies`, `/health` → `:8000`)

---

## Repository Layout (actual)

```
unhinted-marketing/
├── cmd/
│   ├── api/              # FastAPI app + /auth, /signals, /questions, /sessions routes
│   ├── worker/           # hot-search, questions, promote, signals CLI
│   └── scheduler/        # Periodic ingest + question generation
├── internal/
│   ├── auth/             # JWT, passwords, refresh tokens, org access
│   ├── llm/              # LiteLLM BYOK router
│   ├── memory/           # SQLAlchemy models + repos + persona seed
│   ├── perception/       # hot_search, question_generator, news_promoter
│   ├── session/          # LangGraph graph, nodes, Postgres checkpointer, SSE bus
│   └── config.py
├── schemas/              # Pydantic (auth, perception, session)
├── migrations/           # Alembic (auth → signals → sessions)
├── web/                  # React frontend (shell only until Phase 3 UI)
└── docs/
    ├── ROADMAP.md
    ├── GETTING_STARTED.md
    └── STATUS.md             # this file
```

**Not present yet:** `tests/`.

---

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `JWT_SECRET` | Sign access/refresh tokens — **change in prod** |
| `CORS_ORIGINS` | Default `http://localhost:5173` |
| `OPENAI_API_KEY` | LLM for questions + session nodes |
| `LLM_API_BASE` | Optional OpenAI-compatible proxy base URL |
| `ANTHROPIC_API_KEY` | Optional alternate provider |
| `LLM_CHEAP_MODEL` / `LLM_MEDIUM_MODEL` / `LLM_STRONG_MODEL` | LiteLLM tiers |
| `LLM_TIMEOUT_SECONDS` | LiteLLM call timeout (default 45) |
| `QUESTION_CACHE_TTL_HOURS` | Recommended questions cache (default 12) |

See `.env.example`. Local `.env` is gitignored.

---

## Known Gaps / Next Steps

1. **Phase 3 UI (active):** ~~Agent progress/brief UI~~ → ~~Landing cards~~ → Preview + Confirm. Chat shell + `message.delta` streaming + Agent progress/brief/interrupt cards + landing recommended questions shipped. Known gap: no `GET /sessions/{id}/messages` (page refresh loses transcript).
2. **Phase 2 held:** Image worker (replace `placeholder://`), `query_market_trends` JSON Schema, formal curl exit-criteria script.
3. **Phase 3 later:** Meta Graph API ingest, BYOK settings page, trace viewer.
4. **Hardening:** Auth rate limits, basic API tests, multi-worker SSE (Redis) if scaling beyond one API process.

---

## Definition of Done (MVP) — checklist

From ROADMAP; current completion:

1. HK hot search ingests automatically — ✅ (worker + scheduler)  
2. Landing shows ≥5 recommended questions (~12h cache) — ✅ API; ✅ UI (Phase 3 empty-state cards)  
3. User can register, login, access protected dashboard — ✅  
4. Chat → can/cannot recommendation → preview — ✅ API; chat UI ✅ (streaming); brief/preview UI ⬜  
5. Unlimited preview revisions + reviewer gate — ✅ API; ⬜ UI (Phase 3)  
6. Confirm posts via platform API + receipt — 🟡 stub confirm + `tool_receipts`; real publish Phase 4; ⬜ UI button  
7. Claims traceable to `source_signal_ids` — ✅ session grounding in graph; ⬜ UI trace links  

---

## References

- [ROADMAP.md](./ROADMAP.md) — full architecture & phase plan
- [GETTING_STARTED.md](./GETTING_STARTED.md) — local setup & run commands
- [README.md](../README.md) — project intro
