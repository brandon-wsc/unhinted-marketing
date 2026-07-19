# Unhinted Marketing — Project Status

> **Last updated:** 2026-07-19  
> **Overall:** Phase 0 largely complete · Phase 1+ not started  
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
| HK hot search ingestion | ⬜ Not started |
| LangGraph session / preview / confirm | ⬜ Not started |
| pgvector on dev DB | ⬜ Not installed yet |

**Current user-facing flow:** Register or login → protected dashboard placeholder. No marketing agent, chat, or publish yet.

---

## Phase Progress

### Phase 0 — Project Bootstrap · **~90%**

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
| README | ✅ | Quick start included |
| `docker-compose.yml` | ➖ | Removed — dev DB is external |
| Auth rate limiting | ⬜ | Planned (Redis or in-memory) |
| Automated tests | ⬜ | No `tests/` yet |

### Phase 1 — Data & Autopilot Backend · **0%**

Not started: `raw_news_events`, hot search worker, question generator, OKF scaffold, LiteLLM BYOK loader.

### Phase 2 — LangGraph Session + API · **0%**

Not started: `sessions`, `session_messages`, `preview_drafts`, LangGraph graph, SSE, confirm handler.

### Phase 3 — React Dashboard (product UI) · **~10%**

Shell only: auth pages, header, theme/i18n, dashboard cards showing user/org info. No chat, preview, or confirm UI.

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/auth`)
- **Security:** Argon2 password hashing, refresh token rotation + revoke on logout
- **Multi-tenant bootstrap:** Register auto-creates `entities` (type `company`) + `organization_members` (role `owner`)

**Run:**

```bash
source .venv/bin/activate
alembic upgrade head
uvicorn cmd.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Database (dev)

| Table | Purpose |
|-------|---------|
| `users` | Accounts |
| `entities` | Companies (and future entity types) |
| `organization_members` | User ↔ company RBAC |
| `refresh_tokens` | Hashed refresh token families |

**Not migrated yet:** `sessions`, `raw_news_events`, `preview_drafts`, `recommended_questions`, etc.

**pgvector:** Not installed on `192.168.5.20:5434` as of last check. Required before Phase 1 embeddings; ops will install on dev server.

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
├── cmd/api/              # FastAPI app + /auth routes
├── internal/
│   ├── auth/             # JWT, passwords, refresh tokens
│   ├── memory/           # SQLAlchemy models + DB session
│   └── config.py
├── schemas/              # Pydantic (auth)
├── migrations/           # Alembic (001_auth only)
├── web/                  # React frontend
│   ├── public/logo.svg
│   └── src/
│       ├── components/   # header, auth layout, user menu
│       ├── context/      # auth, theme
│       ├── i18n/         # zh-HK
│       └── pages/        # login, register, dashboard
└── docs/
    ├── ROADMAP.md
    └── STATUS.md         # this file
```

**Not present yet:** `cmd/worker`, `cmd/scheduler`, `internal/session`, `internal/perception`, `knowledge/`, `tests/`.

---

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `JWT_SECRET` | Sign access/refresh tokens — **change in prod** |
| `CORS_ORIGINS` | Default `http://localhost:5173` |

See `.env.example`. Local `.env` is gitignored.

---

## Known Gaps / Next Steps

1. **Install pgvector** on dev PostgreSQL before Phase 1 migrations.
2. **Phase 1:** Hot search worker (Google Trends HK + News RSS) → `raw_news_events`; question cache API.
3. **Phase 2:** LangGraph session graph + `POST /sessions`, SSE preview updates, stub confirm.
4. **Phase 3:** Replace dashboard placeholder with chat → agent → preview → confirm UI.
5. **Hardening:** Auth rate limits, `JWT_SECRET` rotation guidance, basic API tests.

---

## Definition of Done (MVP) — checklist

From ROADMAP; current completion:

1. HK hot search ingests automatically — ⬜  
2. Landing shows ≥5 recommended questions (~12h cache) — ⬜  
3. User can register, login, access protected dashboard — ✅  
4. Chat → can/cannot recommendation → preview — ⬜  
5. Unlimited preview revisions + Critic gate — ⬜  
6. Confirm posts via platform API + receipt — ⬜  
7. Claims traceable to `source_signal_ids` — ⬜  

---

## References

- [ROADMAP.md](./ROADMAP.md) — full architecture & phase plan
- [README.md](../README.md) — quick start
