# Unhinted Marketing — Project Status

> **Last updated:** 2026-08-02  
> **Overall:** Phase 0–1 complete · Phase 2 **soft-complete** (UI-ready) · Phase 3 UI **~80%** · Security: auth rate limit + confirm user-private idempotency (branch) · Backend pytest ✅ · Frontend Vitest Tier 1/2 ✅ · CI ✅  
> **Dev DB:** `192.168.5.20:5434` / database `unhinted` · **Test DB:** set `TEST_DATABASE_URL` (e.g. `unhinted_test`) for `pytest tests/api`

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
| Agent Mode UI (`agent.progress` + cards) | ✅ Done — action trail persisted on user-message metadata; interrupt CTA survives fail / refresh |
| Landing recommended-question cards | ✅ Done — empty-state cards → `sendMessage` |
| Preview Mode (IG mock + draft editor) | ✅ Done — desktop left chat / right preview; mobile push pages; Confirm auto-flush |
| Manual draft API `POST …/draft` | ✅ Done — no LLM; revision + approval_token |
| Confirm UI → stub `/confirm` | ✅ Done — receipt status in preview panel |
| Chat history (hydrate + Gemini sidebar) | ✅ Done — list / pin / rename / delete; desktop sidebar + mobile record page |
| pgvector on dev DB | ✅ Done (PG 18.4 · `pgvector/pgvector:pg18`; enable with `CREATE EXTENSION vector`) |

**Current user-facing flow:** Register or login → `/` chat → Agent brief/interrupt → Preview Mode (IG mock + editable draft) → Confirm (stub receipt). Meta ingest / BYOK / Trace still deferred.

**Decision (2026-07-29):** Remaining Phase 2 items are **held**; start Phase 3 product UI against the existing session APIs.

**Decision (2026-07-29) — Phase 3 UI build order + UX:**

1. ~~Chat UI shell~~
2. ~~Chat token stream~~
3. ~~Agent Mode UI~~
4. ~~Landing recommended-question cards~~
5. ~~Preview (left chat / right draft) + Confirm button~~

**Decision (2026-07-30) — Preview Mode product contract:** → [ADR 0001](./adr/0001-preview-canonical-draft.md)

- **Canonical draft** — shared `{ caption, hashtags, cta, image_url }`; not per-platform copies; not a markdown editor
- **MVP preview skin = Instagram only** — phone-style feed mock; FB/Threads later as chrome swap on the same fields
- **AI + user both edit** — AI via chat `revise` (reviewer-gated); user via right-panel fields → `POST /sessions/{id}/draft` (no LLM)
- **Confirm UX** — Confirm auto-flushes dirty local edits (`POST /draft` then `POST /confirm` with new token); clean path confirms current token. Optional **Apply** saves a revision without publishing
- **Chat “可以出” ≠ publish** — UI Confirm button only (existing `ack_confirm`)
- **Still deferred** — real image gen, Meta Graph publish, multi-platform switcher

**Decision (2026-07-31) — Mobile workspace layout:**

- **Chat is primary** — default page on `< lg`; desktop (`lg+`) keeps sidebar + chat + preview side-by-side
- **Three pages on mobile** — Record / Chat / Preview as separate full-height views (not stacked)
- **Navigation** — Chat shows top-left history icon → Record; Record / Preview show **上一頁** back to Chat; open Preview from in-chat ready banner (no auto-jump, no bottom tab bar)
- **Still deferred** — history control in the app header top bar (icon currently overlays chat)

**Decision (2026-08-02) — Contracts SSOT entry:** `AGENTS.md` + [ADRs](./adr/) + `schemas/contracts.py` / `schemas/tools.py` + generated `docs/contracts/` + `docs/openapi.json`. REST > SSE locked in [ADR 0002](./adr/0002-rest-source-of-truth-sse-enhancement.md); Confirm without LLM in [ADR 0003](./adr/0003-confirm-without-llm.md).

**Decision (2026-08-02) — Graph mock-LLM CI:** Session node unit tests monkeypatch LLM/repos (no API key on GitHub). Opt-in `node_trace_recording()` for step I/O. CI Tier 1b ≥70% on `nodes` + `trace`. Live LLM eval stays manual/nightly.

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
| `docker-compose.yml` | ✅ | Local `db` (pgvector) + `minio` / `minio-init` (S3-compatible media) + adminer |
| Auth rate limiting | ✅ | In-memory sliding window on register/login/refresh (`AUTH_RATE_LIMIT_*`); Redis later |
| Automated tests | ✅ Backend + FE Tier 1/2 + CI | BE: `tests/unit` + `tests/api` (`TEST_DATABASE_URL`). FE: `cd web && npm test` (Vitest + RTL — lib utils + PasswordBox / UserMenuDropdown). Policy [TESTING.md](./TESTING.md). CI: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

### Phase 1 — Data & Autopilot Backend · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Alembic `5dae474953cd` (signals) | ✅ | `raw_news_events`, `edges`, `recommended_questions` |
| Hot search worker | ✅ | `python -m cmd.worker hot-search` (Google Trends HK) |
| Question generator | ✅ | LiteLLM + 12h cache; template fallback without API key |
| News promoter | ✅ | Top trends → topic `entities` + `edges` in PG |
| LiteLLM BYOK loader | ✅ | Env-based (`OPENAI_API_KEY`, model tiers); `LLM_API_BASE` → `openai/<model>` prefix |
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
| Migrations | ✅ | Alembic `526ca8643303` sessions tables; `86f20bd3cb7d` session `title` + `pinned` |
| LangGraph graph + interrupt | ✅ | `interrupt_before=executor_image_plan`; resume via `POST /messages` (blind resume while parked is a known follow-up) |
| Postgres checkpointer | ✅ | `AsyncPostgresSaver` + pool (`check` / keepalives / idle recycle); `setup()` on API lifespan; `thread_id = session.id` |
| Node logic | ✅ | LiteLLM + structured I/O; heuristic fallbacks; PG load/grounding |
| Session HTTP API | ✅ | `GET/POST /sessions`, `PATCH/DELETE /sessions/{id}`, `/messages`, `/draft`, `/confirm` |
| SSE `/events` | ✅ | Snapshot + live fan-out; `preview.updated` includes `copy` + `platform`; snapshot `interrupted` from graph checkpoint (+ `sessions.state.awaiting_image_ok`) |
| Image generation worker | 🟡 Soft | LiteLLM ``aimage_generation`` via ``LLM_IMAGE_MODEL``; chat-only / unset → ``llm.failed``. ``data:`` results upload to S3-compatible store (MinIO) when ``S3_*`` configured; else remain data URLs. ``placeholder`` / no credentials → mock URL |
| `query_market_trends` tool schema | ✅ | Pydantic + JSON Schema in `schemas/tools.py` / `docs/contracts/`; node adapter wiring still held |
| Curl exit-criteria script | ⏸ **Held** | Manual/API path works; formal curl checklist later |

**Held Phase 2 work does not block Phase 3 UI.**

### Phase 3 — React Dashboard + Meta Signals · **~80% · IN PROGRESS**

**Focus now:** Meta ingest / BYOK / Trace (core session UI shipped — chat → agent → preview → confirm + history).

| Item | Status | Notes |
|------|--------|-------|
| Auth pages + protected shell | ✅ | Login / register; `/` is now the chat workspace |
| Chat UI shell | ✅ | `web/src/features/session/` — `useSession` + message list / composer; Streamdown + `@streamdown/cjk`; Vite proxy covers `/sessions` `/companies` `/signals` |
| Chat token stream (`message.delta`) | ✅ | `chat` node streams LiteLLM → batched live deltas via event bus; first message waits for SSE open before POST |
| Agent Mode UI | ✅ | `agent.progress` live inside each graph node; Cursor-style action-record trail persisted on the triggering user row as `session_messages.metadata.agent_actions` (hydrate on reopen); brief card + interrupt card (`draft.awaiting_image_ok` / snapshot `interrupted`); resume image gen via `POST /messages` — CTA kept on network/LLM fail while graph still parked |
| Landing: recommended questions cards | ✅ | Empty-state cards from `GET /companies/{id}/recommended-questions`; click → `sendMessage` (start intent); soft-fail on 404 / network |
| Preview Mode (left chat / right preview) | ✅ | Desktop: IG mock + editable fields beside chat. Mobile (`< lg`): Preview is a push page with **上一頁**; open from chat ready banner |
| Confirm button → `/confirm` | ✅ | Dirty auto-flush → draft then confirm; stub receipt in panel |
| Manual draft API `POST …/draft` | ✅ | No LLM; bump revision + `approval_token`; sync graph checkpoint |
| Chat history hydrate + list | ✅ | `GET /sessions`, `GET …/messages`, `PATCH/DELETE …/{id}` (`title`/`pinned`); localStorage last session; desktop Gemini-style sidebar; mobile Record page (history icon → full list; **上一頁** back to Chat) |
| Meta Graph API hot search | ⏸ | Next after core UI |
| BYOK settings page | ⏸ | After core UI |
| Trace viewer | ⏸ | After core UI |

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/auth`)
- **Signals:** `GET /signals/top` — latest HK market signals from PostgreSQL
- **Questions:** `GET /companies/{id}/recommended-questions` — cached 12h question batch
- **Sessions:** `GET /sessions`, `POST /sessions`, `PATCH /sessions/{id}` (title / pinned), `DELETE /sessions/{id}`, `POST /sessions/{id}/messages`, `GET /sessions/{id}/messages`, `POST /sessions/{id}/draft`, `GET /sessions/{id}/events` (SSE), `POST /sessions/{id}/confirm`
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
| `sessions` | Chat session (mode, user_id, company_id, title, pinned, state JSONB) |
| `session_messages` | Chat log (user always; assistant for chat / ack / LLM errors — not every Agent node) |
| `preview_drafts` | Revision chain + approval_token |
| `tool_receipts` | Idempotent Confirm / tool receipts |
| LangGraph checkpoint tables | Owned by `AsyncPostgresSaver.setup()` (not Alembic) |

**pgvector:** Dev DB on Synology NAS runs **`pgvector/pgvector:pg18`** (PostgreSQL **18.4**). PG 18+ Docker images mount data at **`/var/lib/postgresql`** (not `/var/lib/postgresql/data`). After restore/migrate, run `CREATE EXTENSION vector;` on `unhinted`.

### Frontend (`web/`)

| Route | Description |
|-------|-------------|
| `/login` | Email/password login |
| `/register` | Sign up + default workspace |
| `/` | Protected **chat workspace** — desktop history sidebar + chat (+ preview); mobile Record / Chat / Preview pages |

**UX features:**

- **Header:** Logo + brand name (top-left); user menu dropdown (top-right) with language, theme, logout
- **i18n:** `react-i18next`, locale `zh-HK`, keys in English in `web/src/i18n/locales/zh-HK.json` — extensible via `SUPPORTED_LOCALES`
- **Theme:** Light / dark / system, persisted in `localStorage`
- **Form memory:** Last user email / display name / org name from `localStorage` (not fake placeholders)
- **Auth:** Access token in memory; refresh via cookie; auto-refresh on app load
- **Phase 3 (shipped):** Chat workspace at `/` — `useSession` REST-first + SSE; Streamdown + `@streamdown/cjk`; live `message.delta`; Agent Mode UI (`agent.progress` trail persisted on user-message `metadata.agent_actions`; brief / `draft.awaiting_image_ok` interrupt; snapshot `interrupted` rehydrates Generate-image CTA); landing recommended-question cards; IG Preview + Confirm; Gemini-style history (desktop sidebar; mobile Record push page); mobile Chat primary with history icon + Preview via ready banner / **上一頁**; `llm.failed` inline error + Retry; shell fits `h-dvh` with per-pane scroll; no `useChat`
- **Session client:** `web/src/features/session/` — `api.ts` (REST), `sse.ts` (`@microsoft/fetch-event-source` with Bearer), `use-session.ts`, `session-storage.ts` (per-company last session id), `use-recommended-questions.ts`, `components/chat-panel.tsx` + `session-history.tsx` + `preview-panel.tsx` + `ig-preview-mock.tsx` + `recommended-questions.tsx`
- **Chat persistence:** Backend writes `session_messages` (user always; assistant for `chat` / `ack_confirm` / LLM failure / review exhausted). Agent turns often **do not** append assistant chat rows — brief/draft live in `sessions.state` + `preview_drafts`. **Agent action trail:** after each turn, `agent.progress` payloads are stored on that turn’s **user** message as `metadata.agent_actions` (`[{node, model_tier, model}, …]`); `GET …/messages` returns `metadata` so refresh rebuilds the trail. **Interrupt hydrate:** `sessions.state.awaiting_image_ok` + SSE `session.snapshot.interrupted` (graph `next`) restore the Generate-image card after reopen / API drop. **Hydrate:** `GET /sessions/{id}/messages` + remembered session id in `localStorage`. **History:** desktop left sidebar lists `GET /sessions?company_id=` (pinned group + date groups + search); mobile opens the same list as a full-page Record view; `PATCH` rename/pin, `DELETE` removes session (+ cascades).

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
├── schemas/              # Pydantic (auth, perception, session, contracts, tools)
├── scripts/              # export_contracts → docs/openapi.json + docs/contracts/
├── migrations/           # Alembic (auth → signals → sessions)
├── tests/                # pytest: unit (no DB) + api (TEST_DATABASE_URL)
├── web/                  # React frontend (Phase 3 chat / agent / preview / history UI)
├── AGENTS.md             # Coding-agent SSOT map
└── docs/
    ├── ROADMAP.md
    ├── GETTING_STARTED.md
    ├── TESTING.md            # path-tiered coverage gates
    ├── STATUS.md             # this file
    ├── adr/                  # Architecture Decision Records
    ├── contracts/            # JSON Schema mirrors (generated)
    └── openapi.json          # FastAPI OpenAPI (generated)
```

**Tests:** `tests/unit` (no DB) · `tests/api` (requires `TEST_DATABASE_URL`) · `cd web && npm test` (Vitest Tier 1/2). Policy: [TESTING.md](./TESTING.md).

---

## Environment

| Variable | Purpose |
|----------|---------|
| `TEST_DATABASE_URL` | Isolated Postgres for `pytest tests/api` (skipped if unset) |
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `APP_ENV` | `development` (default) or `production` — production refuses weak JWT |
| `ALLOW_INSECURE_JWT` | Escape hatch for local/tests only (`true` skips JWT secret check) |
| `JWT_SECRET` | Sign access/refresh tokens — **≥32 chars + unique** (prod rejects the published `.env.example` default) |
| `AUTH_RATE_LIMIT_ENABLED` | Rate-limit `/auth/register|login|refresh` (default true) |
| `AUTH_RATE_LIMIT_MAX` | Max requests per client IP per window (default 30) |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Sliding window length (default 60) |
| `CORS_ORIGINS` | Default `http://localhost:5173` |
| `OPENAI_API_KEY` | LLM for questions + session nodes |
| `LLM_API_BASE` | Optional OpenAI-compatible proxy base URL (OpenRouter, DeepSeek, Azure, …). When set, bare model ids are sent as `openai/<id>` so LiteLLM uses the OpenAI-compatible client against that base (avoids native Deepseek routing ignoring `api_base`) |
| `ANTHROPIC_API_KEY` | Optional alternate provider |
| `LLM_CHEAP_MODEL` / `LLM_MEDIUM_MODEL` / `LLM_STRONG_MODEL` | Provider model ids (e.g. `gpt-4o-mini`, `deepseek-chat`) |
| `LLM_IMAGE_MODEL` | Image-capable id (e.g. `dall-e-3` / OpenRouter image model). Unset with credentials → error on gen; `placeholder` = mock URL |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | S3-compatible media (MinIO: `docker compose up -d minio minio-init`). Empty endpoint → skip upload |
| `S3_PUBLIC_BASE_URL` | Browser base for object URLs (default `{endpoint}/{bucket}`) |
| `LLM_TIMEOUT_SECONDS` | LiteLLM call timeout (default 45) |
| `QUESTION_CACHE_TTL_HOURS` | Recommended questions cache (default 12) |

See `.env.example`. Local `.env` is gitignored.

---

## Known Gaps / Next Steps

### High-priority risks

| ID | Risk | Status |
|----|------|--------|
| **H1** | Auth rate limit + known-default / weak `JWT_SECRET` | ✅ **Mitigated on this branch** — in-memory limit on register/login/refresh; `APP_ENV=production` refuses insecure JWT |
| **H2** | Interrupt resume ignores user intent (`ainvoke(None)`) | ⬜ Open — product decision + ADR before change |
| **H3** | `use-session.ts` correctness concentrated & untested | ⬜ Open — extract pure helpers + Tier 6 tests |
| **I1** | Confirm idempotency key global (cross-user receipt leak) | ✅ **Mitigated** — foreign key → 409; same session/user only replays |

### Other gaps

1. **Phase 3 UI:** Core chat → agent action records (DB-backed on user-message metadata) → preview → confirm stub + history (desktop sidebar / mobile Record–Chat–Preview push pages) shipped. Agent path still rarely writes assistant chat bubbles (brief/preview are side-channel UI). Interrupt Generate-image CTA rehydrates from graph/SSE after fail or refresh.
2. **Phase 2 soft / held:** Image gen via `LLM_IMAGE_MODEL` + MinIO (`S3_*`) when configured; formal curl exit-criteria script still later; `query_market_trends` **schema** landed — adapter wiring still held.
3. **Phase 3 later:** Meta Graph API ingest, BYOK settings page, trace viewer; FB/Threads preview skins.
4. **Hardening:** ~~Auth rate limits + JWT secret guard~~ + ~~confirm idempotency user/session scope~~; ~~basic API tests~~ + ~~frontend Vitest Tier 1/2~~ + ~~CI~~ ([TESTING.md](./TESTING.md), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)); ~~contracts SSOT~~ ([AGENTS.md](../AGENTS.md), [adr/](./adr/), [contracts/](./contracts/)); ~~mock-LLM graph node tests + CI Tier 1b~~; multi-worker SSE (Redis) if scaling beyond one API process; media private/signed URLs; re-check org membership on session access after revoke; enable branch protection requiring CI checks; persist node traces / live LLM eval harness later.

---

## Definition of Done (MVP) — checklist

From ROADMAP; current completion:

1. HK hot search ingests automatically — ✅ (worker + scheduler)  
2. Landing shows ≥5 recommended questions (~12h cache) — ✅ API; ✅ UI (Phase 3 empty-state cards)  
3. User can register, login, access protected dashboard — ✅  
4. Chat → can/cannot recommendation → preview — ✅ API; ✅ chat/brief/preview UI  
5. Unlimited preview revisions + reviewer gate — ✅ API (AI revise); ✅ UI + manual `POST /draft`  
6. Confirm posts via platform API + receipt — 🟡 stub confirm + UI receipt; real publish Phase 4  
7. Claims traceable to `source_signal_ids` — ✅ session grounding in graph; ⬜ UI trace links  

---

## References

- [ROADMAP.md](./ROADMAP.md) — full architecture & phase plan
- [GETTING_STARTED.md](./GETTING_STARTED.md) — local setup & run commands
- [TESTING.md](./TESTING.md) — test tiers & path coverage gates
- [README.md](../README.md) — project intro
