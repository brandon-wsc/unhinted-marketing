# Unhinted Marketing — Project Status

> **Last updated:** 2026-07-26  
> **Overall:** Phase 0 complete · Phase 1 complete · Phase 2 not started  
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
| LangGraph session / preview / confirm | ⬜ Not started |
| pgvector on dev DB | ✅ Done (PG 18.4 · `pgvector/pgvector:pg18`; enable with `CREATE EXTENSION vector`) |

**Current user-facing flow:** Register or login → protected dashboard placeholder. Backend workers can ingest HK signals and serve cached recommended questions via API. No chat or publish UI yet.

---

## Phase Progress

### Phase 0 — Project Bootstrap · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Git repo | ✅ | |
| `docs/ROADMAP.md` | ✅ | |
| `docs/STATUS.md` | ✅ | This file |
| `.env.example` | ✅ | Points to dev DB `192.168.5.20:5434` |
| `pyproject.toml` + Python skeleton | ✅ | FastAPI, SQLAlchemy, Alembic, JWT |
| Auth API | ✅ | `/auth/register`, `/login`, `/refresh`, `/logout`, `/me` |
| Alembic `001_auth` | ✅ | `users`, `entities`, `organization_members`, `refresh_tokens` |
| React web app | ✅ | Vite + React 19 + Tailwind v4 |
| README | ✅ | Project intro; setup in GETTING_STARTED |
| `docker-compose.yml` | ➖ | Removed — dev DB is external |
| Auth rate limiting | ⬜ | Planned (Redis or in-memory) |
| Automated tests | ⬜ | No `tests/` yet |

### Phase 1 — Data & Autopilot Backend · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Alembic `002_phase1` | ✅ | `raw_news_events`, `edges`, `recommended_questions` |
| Hot search worker | ✅ | `python -m cmd.worker hot-search` (Google Trends HK) |
| Question generator | ✅ | LiteLLM + 12h cache; template fallback without API key |
| News promoter | ✅ | Top trends → topic `entities` + `edges` in PG |
| LiteLLM BYOK loader | ✅ | Env-based (`OPENAI_API_KEY`, model tiers) |
| Default personas | ✅ | Seeded in `entities` (type=persona) on first question run |
| Signals API | ✅ | `GET /signals/top` |
| Questions API | ✅ | `GET /companies/{id}/recommended-questions` |
| Scheduler | ✅ | `python -m cmd.scheduler` |
| CLI signals | ✅ | `python -m cmd.worker signals` |

### Phase 2 — LangGraph Session + API · **0%**

Not started: `sessions`, `session_messages`, `preview_drafts`, LangGraph graph (see ROADMAP node list: `trend_searcher`, `brainstormer`, `executor_post`, `executor_image_*`, `reviewer`, …), SSE, confirm handler.

### Phase 3 — React Dashboard + Meta Signals (product UI) · **~10%**

Shell only: auth pages, header, theme/i18n, dashboard cards showing user/org info. No chat, preview, confirm UI, or Meta signal ingest yet.

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/auth`)
- **Signals:** `GET /signals/top` — latest HK market signals from PostgreSQL
- **Questions:** `GET /companies/{id}/recommended-questions` — cached 12h question batch
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

Set `OPENAI_API_KEY` in `.env` for LLM-generated questions; without it, template fallbacks are used.

### Database (dev)

| Table | Purpose |
|-------|---------|
| `users` | Accounts |
| `entities` | Companies (and future entity types) |
| `organization_members` | User ↔ company RBAC |
| `refresh_tokens` | Hashed refresh token families |
| `raw_news_events` | Ingested HK signals (Google Trends HK; Meta API in Phase 3) |
| `edges` | Graph links (signal → topic entities) |
| `recommended_questions` | 12h cached landing question JSON |

**Not migrated yet:** `sessions`, `preview_drafts`, `tool_receipts`, etc.

**pgvector:** Dev DB on Synology NAS runs **`pgvector/pgvector:pg18`** (PostgreSQL **18.4**). PG 18+ Docker images mount data at **`/var/lib/postgresql`** (not `/var/lib/postgresql/data`). After restore/migrate, run `CREATE EXTENSION vector;` on `unhinted`.

### Frontend (`web/`)

| Route | Description |
|-------|-------------|
| `/login` | Email/password login |
| `/register` | Sign up + default workspace |
| `/` | Protected dashboard (placeholder) |

**UX features:**

- **Header:** Logo + brand name (top-left); user menu dropdown (top-right) with language, theme, logout
- **i18n:** `react-i18next`, locale `zh-HK`, keys in English in `web/src/i18n/locales/zh-HK.json` — extensible via `SUPPORTED_LOCALES`
- **Theme:** Light / dark / system, persisted in `localStorage`
- **Form memory:** Last user email / display name / org name from `localStorage` (not fake placeholders)
- **Auth:** Access token in memory; refresh via cookie; auto-refresh on app load

**Run:**

```bash
cd web && npm install && npm run dev
```

App: http://localhost:5173/login (Vite proxies `/auth` → `:8000`)

---

## Repository Layout (actual)

```
unhinted-marketing/
├── cmd/
│   ├── api/              # FastAPI app + /auth, /signals, /questions routes
│   ├── worker/           # hot-search, questions, promote, signals CLI
│   └── scheduler/        # Periodic ingest + question generation
├── internal/
│   ├── auth/             # JWT, passwords, refresh tokens, org access
│   ├── llm/              # LiteLLM BYOK router
│   ├── memory/           # SQLAlchemy models + repos + persona seed
│   ├── perception/       # hot_search, question_generator, news_promoter
│   └── config.py
├── schemas/              # Pydantic (auth, perception)
├── migrations/           # Alembic (001_auth, 002_phase1)
├── web/                  # React frontend
└── docs/
    ├── ROADMAP.md
    ├── GETTING_STARTED.md  # local setup & API overview
    └── STATUS.md             # this file
```

**Not present yet:** `internal/session`, `tests/`.

---

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `JWT_SECRET` | Sign access/refresh tokens — **change in prod** |
| `CORS_ORIGINS` | Default `http://localhost:5173` |
| `OPENAI_API_KEY` | LLM question generation (optional; fallback templates without) |
| `LLM_CHEAP_MODEL` | Cheap tier model for workers (default `gpt-4o-mini`) |
| `QUESTION_CACHE_TTL_HOURS` | Recommended questions cache (default 12) |

See `.env.example`. Local `.env` is gitignored.

---

## Known Gaps / Next Steps

1. **Phase 2:** LangGraph session graph (`trend_searcher` → `brainstormer` → `executor_post` → `reviewer` → `executor_image_*`); `POST /sessions`, SSE preview updates, stub confirm.
2. **Phase 3:** Meta Graph API hot search worker; React dashboard (chat → preview → confirm UI); wire recommended questions cards.
3. **Hardening:** Auth rate limits, `JWT_SECRET` rotation guidance, basic API tests.

---

## Definition of Done (MVP) — checklist

From ROADMAP; current completion:

1. HK hot search ingests automatically — ✅ (worker + scheduler)  
2. Landing shows ≥5 recommended questions (~12h cache) — ✅ (API; UI in Phase 3)  
3. User can register, login, access protected dashboard — ✅  
4. Chat → can/cannot recommendation → preview — ⬜  
5. Unlimited preview revisions + reviewer gate — ⬜  
6. Confirm posts via platform API + receipt — ⬜  
7. Claims traceable to `source_signal_ids` — ⬜ (signals stored; session grounding in Phase 2)  

---

## References

- [ROADMAP.md](./ROADMAP.md) — full architecture & phase plan
- [GETTING_STARTED.md](./GETTING_STARTED.md) — local setup & run commands
- [README.md](../README.md) — project intro
