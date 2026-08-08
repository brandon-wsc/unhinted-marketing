# Unhinted Marketing — Project Status

> **Last updated:** 2026-08-08  
> **Overall:** Phase 0–1 complete · Phase 2 **soft-complete** (UI-ready) · Phase 3 UI **~80%** · Craft: default HK 小編 + `roast_level` ([VOICE.md](./VOICE.md)) · Preview media append-only ([ADR 0008](./adr/0008-preview-images-append-only.md)) · Security: auth rate limit + confirm user-private idempotency · Observability: LLM call records + platform levels ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)) · Backend pytest ✅ · Frontend Vitest Tier 1/2 ✅ · CI ✅  
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
| Preview Mode (IG mock + draft editor) | ✅ Done — Edit Copy / Edit Image dialogs; multi-image carousel; mobile push pages; Confirm auto-flush |
| Manual draft API `POST …/draft` | ✅ Done — no LLM; revision + approval_token |
| Confirm UI → stub `/confirm` | ✅ Done — receipt status in preview panel |
| Chat history (hydrate + Gemini sidebar) | ✅ Done — list / pin / rename / delete; desktop sidebar + mobile record page |
| pgvector on dev DB | ✅ Done (PG 18.4 · `pgvector/pgvector:pg18`; enable with `CREATE EXTENSION vector`) |

**Decision (2026-08-08) — Chat research gate + Tavily∪PG:** → [ADR 0009](./adr/0009-research-gate-and-tavily-ingest.md)

- **Unified `route_intent`** — one structured call: `graph_intent` + `research` (`need_facts` / `ambiguous` / `ask_clarify`); no separate graph-routing classifier
- **`fast_rule_checker`** — semantic-router + FastEmbed (multilingual MiniLM; e5-small not in FastEmbed registry) with regex fallback; only `need_search` → `research_rule_pass`
- **Both sources** — research always uses PostgreSQL **and** Tavily; do not skip Tavily on PG hit; both land in `raw_news_events`
- **Act ≠ search** — `start` / revise gated on clear intent (+ clarify if ambiguous), not on Tavily success; **ambiguity does not block research** — searchable phrases search best-effort first; ask_clarify is for drafting, not a quiz instead of search
- **Implementation** — in progress on `feat/session-research-tavily` (schema, nodes, `TAVILY_API_KEY`, semantic-router)

**Decision (2026-08-04) — Default HK social craft + roast_level:** → [VOICE.md](./VOICE.md)

- **Default craft** — 港式小編 (IKEA feel × Duolingo short/sharp): 貼地 · 有鉤 · 有畫面 · 短 · 有邊界
- **Tunable** — `entities.profile.roast_level` 0–3 (missing → 1); injected as `company_context.voice` in `load_context`
- **Prompts** — `BRAINSTORM` / `EXECUTOR_POST` / `EDIT_COPY` / `REVIEWER` share craft block + few-shots; chat stays assistant voice

**Decision (2026-08-05) — Image visual format (no new graph node):**

- **Formats** — `image_format`: `single` (default) | `comic_4panel` (one PNG strip); still one strip PNG per comic asset
- **Where** — same `executor_image_plan` / `executor_image_gen`; plan schema gains `format` + optional `panels[]`
- **Image format:** `single` (default) or `comic_4panel` via Generate-image chips / `POST /resume-image` body; revise text「4格」also sets format
- **Comic craft:** panels 1–3 situational empathy (no product); panel 4 soft remedy — see [VOICE.md](./VOICE.md) §5 Unhinted Market

**Decision (2026-08-05) — Append-only preview images:** → [ADR 0008](./adr/0008-preview-images-append-only.md)

- **`preview_images`** + **`preview_drafts.media_ids`** `uuid[]`; publishable change → new draft; plan/regen/add → new image row
- Compat: `image_url` / `image_plan` denormalized primary; SSE `preview.updated` includes `media[]`
- **HTTP + Preview UI:** `GET/POST /sessions/{id}/media`, `PATCH .../media/{id}/plan`, `POST .../media/{id}/regen`, `POST .../media/{id}/remove`, `POST .../media/{id}/upload`; Edit Image dialog (Select, uploader, Generate/Regenerate, Delete); Edit Copy dialog from IG mock (caption / hashtags / CTA); multi-image carousel when `media[]` length > 1

**Current user-facing flow:** Register or login → `/` chat → Agent brief/interrupt → Preview Mode (IG mock + Edit Copy / Edit Image) → Confirm (stub receipt). Meta ingest / BYOK / Trace still deferred.

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

**Decision (2026-07-31) — Mobile workspace layout:** *(superseded layout trigger 2026-08-06 — see content-based shell below; UX pages unchanged)*

- **Chat is primary** — default page in paged mode; split mode keeps sidebar + chat + preview side-by-side
- **Three pages when paged** — Record / Chat / Preview as separate full-height views (not stacked)
- **Navigation** — Chat shows top-left history icon → Record; Record / Preview show **上一頁** back to Chat; open Preview from in-chat ready banner (no auto-jump, no bottom tab bar)
- **Still deferred** — history control in the app header top bar (icon currently overlays chat)

**Decision (2026-08-02) — Contracts SSOT entry:** `AGENTS.md` + [ADRs](./adr/) + `schemas/contracts.py` / `schemas/tools.py` + generated `docs/contracts/` + `docs/openapi.json`. REST > SSE locked in [ADR 0002](./adr/0002-rest-source-of-truth-sse-enhancement.md); Confirm without LLM in [ADR 0003](./adr/0003-confirm-without-llm.md).

**Decision (2026-08-02) — Graph mock-LLM CI:** Session node unit tests monkeypatch LLM/repos (no API key on GitHub). Opt-in `node_trace_recording()` for step I/O. CI Tier 1b ≥70% on `nodes` + `trace`. Live LLM eval stays manual/nightly.

**Decision (2026-08-03) — Platform levels + LLM call records:** → [ADR 0005](./adr/0005-platform-levels-and-llm-records.md)

- **Platform privilege** — numeric `users.platform_level` ladder 0–10 with named rungs + gaps (`MEMBER`=3 default, `ADMIN`=6 read-only records, `SUPERADMIN`=9 full); threshold checks via `require_platform_level`; tenant `organization_members.role` stays separate
- **Bootstrap** — CLI only: `python -m cmd.worker set-platform-role --email … --level superadmin`
- **LLM call records** — every provider call (10 session LLM nodes + `question_generator` worker) persisted to `llm_call_records` with prompts, response, tokens, latency, status, `parse_ok` / `fallback_used`; instrumented at the `internal/llm/router.py` choke point; correlation via contextvars; toggle `LLM_RECORD_ENABLED` (default on)
- **Admin surface** — `GET /api/admin/llm-calls` (+ `/{id}`), `GET /api/admin/node-steps` (+ `/{id}`), `GET /api/admin/sessions/{id}/trace`, `GET /api/admin/sessions/{id}/research` gated by `require_platform_level(ADMIN)`; web `/admin` (UserMenu, level ≥ 6) with tabs: LLM calls | Node steps | Research | Session Trace ([ADR 0007](./adr/0007-admin-trace-viewer.md))

**Decision (2026-08-03) — API `/api` prefix vs SPA proxy collision:** → [ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md)

- Same-origin vite proxy + top-level API paths (`/admin`, `/sessions`, …) was a **latent namespace footgun**; became user-visible when SPA `/admin` shared a prefix with the API (refresh → FastAPI `{"detail":"Not Found"}`)
- **Executed 2026-08-04:** all public HTTP routes under `/api/…`; vite single proxy `/api` → API; SPA `/admin` refresh serves the React app (API is `/api/admin/*`)

**Decision (2026-08-03) — Admin Trace viewer:** → [ADR 0007](./adr/0007-admin-trace-viewer.md)

- Production `session_node_steps` + `turn_id` correlation with `llm_call_records`; admin tabs Node steps / Session Trace

**Decision (2026-08-06) — Frontend UI system (tokens + shadcn layers):**

- **Primitives** — `web/src/components/ui/*` is the only control stack (shadcn); compose in `components/` / `features/`; no parallel Button/Input/Dialog
- **Tokens** — Prefer semantic utilities (`bg-card`, `text-muted-foreground`, …) from `web/src/index.css` `@theme`; avoid `var(--color-*)` in JSX classNames
- **Session shell layout** — `split` vs `paged` from **container width vs content min-widths** (`session-layout.ts`: history + chat [+ preview]), not viewport `lg` / device names; measured via `useContainerWidth` on the chat shell
- **Agent rule** — [`.cursor/rules/web-ui-system.mdc`](../.cursor/rules/web-ui-system.mdc)
- **Composed helpers** — `FormField`, `IconButton` in `web/src/components/`; menus/confirm via `DropdownMenu` / `AlertDialog`

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
| Auth API | ✅ | `/api/auth/register`, `/login`, `/refresh`, `/logout`, `/me` |
| Alembic `8791b607d5bc` (auth) | ✅ | `users`, `entities`, `organization_members`, `refresh_tokens` |
| React web app | ✅ | Vite + React 19 + Tailwind v4 |
| README | ✅ | Project intro; setup in GETTING_STARTED |
| `docker-compose.yml` | ✅ | Local `db` (pgvector) + `minio` / `minio-init` (S3-compatible media) + adminer |
| Auth rate limiting | ✅ | In-memory sliding window on register/login/refresh (`AUTH_RATE_LIMIT_*`); Redis later |
| Automated tests | ✅ Backend + FE Tier 1/2 + CI | BE: `tests/unit` + `tests/api` (`TEST_DATABASE_URL`). FE: `cd web && pnpm test` (Vitest + RTL — lib utils + `session-helpers` / `session-layout` / `useSession` + PasswordBox / UserMenuDropdown). Policy [TESTING.md](./TESTING.md). CI: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

### Phase 1 — Data & Autopilot Backend · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Alembic `5dae474953cd` (signals) | ✅ | `raw_news_events`, `edges`, `recommended_questions` |
| Hot search worker | ✅ | `python -m cmd.worker hot-search` (Google Trends HK) |
| Question generator | ✅ | LiteLLM + 12h cache; template fallback without API key |
| News promoter | ✅ | Top trends → topic `entities` + `edges` in PG |
| LiteLLM BYOK loader | ✅ | Env-based (`OPENAI_API_KEY`, model tiers); `LLM_API_BASE` → `openai/<model>` prefix |
| Default personas | ✅ | Seeded in `entities` (type=persona) on first question run |
| Signals API | ✅ | `GET /api/signals/top` |
| Questions API | ✅ | `GET /api/companies/{id}/recommended-questions` |
| Scheduler | ✅ | `python -m cmd.scheduler` |
| CLI signals | ✅ | `python -m cmd.worker signals` |

### Phase 2 — LangGraph Session + API · **soft-complete (~65%)**

Backend session loop is **UI-ready**. Graph contract locked in [ROADMAP.md](./ROADMAP.md). Remaining checklist items are **explicitly held** so product UI can ship first.

| Item | Status | Notes |
|------|--------|-------|
| ROADMAP graph contract | ✅ | 12 nodes + `persist_preview`; edges + interrupt |
| Migrations | ✅ | Alembic `526ca8643303` sessions; `86f20bd3cb7d` title/pinned; `7d7a1918bde7` `preview_images` + `media_ids` ([ADR 0008](./adr/0008-preview-images-append-only.md)) |
| LangGraph graph + interrupt | ✅ | `interrupt_before=executor_image_plan`; resume via `POST /resume-image` ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md)); Stop mid-resume re-parks CTA; Stop while parked discards turn |
| Postgres checkpointer | ✅ | `AsyncPostgresSaver` + pool (`check` / keepalives / idle recycle); `setup()` on API lifespan; `thread_id = session.id` |
| Node logic | ✅ | LiteLLM + structured I/O; heuristic fallbacks; PG load/grounding |
| Session HTTP API | ✅ | `GET/POST /api/sessions`, `PATCH/DELETE /api/sessions/{id}`, `/messages`, `/draft`, `/media` (+ plan/regen/remove/upload), `/confirm` |
| SSE `/events` | ✅ | Snapshot + live fan-out; `preview.updated` includes `copy` + `platform` + `media[]`; snapshot hydrates `media` from latest draft |
| Image generation worker | 🟡 Soft | LiteLLM ``aimage_generation`` via ``LLM_IMAGE_MODEL``; chat-only / unset → ``llm.failed``. ``data:`` results upload to S3-compatible store (MinIO) when ``S3_*`` configured; else remain data URLs. ``placeholder`` / no credentials → mock URL |
| `query_market_trends` tool schema | ✅ | Pydantic + JSON Schema in `schemas/tools.py` / `docs/contracts/`; node adapter wiring still held |
| Chat research + Tavily ingest | 🟡 | ADR 0009; semantic-router FastEmbed gate + Tavily adapter; `TAVILY_API_KEY` for live search |
| Curl exit-criteria script | ⏸ **Held** | Manual/API path works; formal curl checklist later |

**Held Phase 2 work does not block Phase 3 UI.**

### Phase 3 — React Dashboard + Meta Signals · **~80% · IN PROGRESS**

**Focus now:** Meta ingest / BYOK / Trace (core session UI shipped — chat → agent → preview → confirm + history).

| Item | Status | Notes |
|------|--------|-------|
| Auth pages + protected shell | ✅ | Login / register; `/` is now the chat workspace |
| Chat UI shell | ✅ | `web/src/features/session/` — `useSession` + message list / composer; Streamdown + `@streamdown/cjk`; Vite proxies `/api` → API |
| Chat token stream (`message.delta`) | ✅ | `chat` node streams LiteLLM → batched live deltas via event bus; first message waits for SSE open before POST |
| Agent Mode UI | ✅ | `agent.progress` live inside each graph node; Cursor-style action-record trail persisted on the triggering user row as `session_messages.metadata.agent_actions` (hydrate on reopen); brief card + interrupt card (`draft.awaiting_image_ok` / snapshot `interrupted`); resume via `POST /resume-image`; composer locked while in-flight or parked; Stop mid-image re-parks Generate-image CTA; Stop while parked discards turn ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md)) |
| Landing: recommended questions cards | ✅ | Empty-state cards from `GET /api/companies/{id}/recommended-questions`; click → `sendMessage` (start intent); soft-fail on 404 / network |
| Preview Mode (left chat / right preview) | ✅ | Split: IG mock + **Edit Copy dialog** + multi-image carousel; **hover/tap image → Edit image**. Paged: Preview push page with **上一頁** (content-width shell, not `lg`) |
| Confirm button → `/confirm` | ✅ | Dirty auto-flush → draft then confirm; stub receipt in panel |
| Manual draft API `POST …/draft` | ✅ | No LLM; bump revision + `approval_token`; caption-only reuses `media_ids` ([ADR 0008](./adr/0008-preview-images-append-only.md)) |
| Preview media APIs | ✅ | `GET/POST …/media`, `PATCH …/media/{id}/plan`, `POST …/media/{id}/regen`, `POST …/media/{id}/remove`, `POST …/media/{id}/upload` — append-only image rows + new draft |
| Chat history hydrate + list | ✅ | `GET /api/sessions`, `GET …/messages`, `PATCH/DELETE …/{id}` (`title`/`pinned`); localStorage last session; desktop Gemini-style sidebar; mobile Record page (history icon → full list; **上一頁** back to Chat) |
| LLM call records + admin page | ✅ | [ADR 0005](./adr/0005-platform-levels-and-llm-records.md) — `llm_call_records` + platform levels + recorder; `/api/admin/llm-calls` API + web `/admin` |
| API `/api` path prefix | ✅ | [ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md) — hard cut; SPA `/admin` refresh no longer collides |
| Admin Trace viewer (node-steps + session) | ✅ | [ADR 0007](./adr/0007-admin-trace-viewer.md) — `session_node_steps` + `turn_id`; admin tabs Node steps / Session Trace |
| Meta Graph API hot search | ⏸ | Next after core UI |
| BYOK settings page | ⏸ | After core UI |
| Trace viewer | ✅ | Admin Session Trace tab ([ADR 0007](./adr/0007-admin-trace-viewer.md)) — not end-user UI |

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /api/health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/api/auth`)
- **Signals:** `GET /api/signals/top` — latest HK market signals from PostgreSQL
- **Questions:** `GET /api/companies/{id}/recommended-questions` — cached 12h question batch
- **Sessions:** `GET /api/sessions`, `POST /api/sessions`, `PATCH /api/sessions/{id}` (title / pinned), `DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/messages`, `GET /api/sessions/{id}/messages`, `POST /api/sessions/{id}/resume-image`, `POST /api/sessions/{id}/stop`, `POST /api/sessions/{id}/draft`, `GET/POST /api/sessions/{id}/media`, `PATCH /api/sessions/{id}/media/{image_id}/plan`, `POST /api/sessions/{id}/media/{image_id}/regen`, `POST /api/sessions/{id}/media/{image_id}/remove`, `POST /api/sessions/{id}/media/{image_id}/upload`, `GET /api/sessions/{id}/events` (SSE), `POST /api/sessions/{id}/confirm`
- **LangGraph:** Session nodes + Postgres checkpointer; image URL still placeholder
- **Security:** Argon2 password hashing, refresh token rotation + revoke on logout
- **Multi-tenant bootstrap:** Register auto-creates `entities` (type `company`) + `organization_members` (role `owner`)
- **Platform levels:** `users.platform_level` ladder ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)); grant via worker CLI `set-platform-role`; `require_platform_level(ADMIN)` gates `/api/admin/*`
- **LLM call records:** Every provider call (session nodes + question worker) → `llm_call_records` (prompts, response, tokens, latency, status, `parse_ok`/`fallback_used`); `LLM_RECORD_ENABLED=false` disables

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
python -m cmd.worker set-platform-role --email you@x.com --level superadmin   # Grant platform level (ADR 0005)
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
| `preview_drafts` | Revision chain + approval_token + `media_ids` |
| `preview_images` | Append-only image versions (url + plan) ([ADR 0008](./adr/0008-preview-images-append-only.md)) |
| `tool_receipts` | Idempotent Confirm / tool receipts |
| `llm_call_records` | Per-call LLM record: correlation, prompts, response, tokens, latency, status, `parse_ok`/`fallback_used` ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)) |
| LangGraph checkpoint tables | Owned by `AsyncPostgresSaver.setup()` (not Alembic) |

**pgvector:** Dev DB on Synology NAS runs **`pgvector/pgvector:pg18`** (PostgreSQL **18.4**). PG 18+ Docker images mount data at **`/var/lib/postgresql`** (not `/var/lib/postgresql/data`). After restore/migrate, run `CREATE EXTENSION vector;` on `unhinted`.

### Frontend (`web/`)

| Route | Description |
|-------|-------------|
| `/login` | Email/password login |
| `/register` | Sign up + default workspace |
| `/` | Protected **chat workspace** — split: history + chat (+ preview); paged: Record / Chat / Preview |
| `/admin` | Platform admin (level ≥ 6) — LLM calls / node steps / session trace |

**UI system:** shadcn under `components/ui/` + semantic tokens in `index.css`; layers in [`.cursor/rules/web-ui-system.mdc`](../.cursor/rules/web-ui-system.mdc). Auth composes `ui/*` + `FormField` / `PasswordBox`; app chrome in `components/` (`AppShell`, `AuthLayout`, `IconButton`). Session shell uses content-width `split`/`paged` (`session-layout.ts`). Lint/format: Biome (`web/biome.json`; `pnpm run lint`).

**UX features:**

- **Header:** Logo + brand name (top-left); user menu dropdown (top-right) with language, theme, logout
- **i18n:** `react-i18next`, locale `zh-HK`, keys in English in `web/src/i18n/locales/zh-HK.json` — extensible via `SUPPORTED_LOCALES`
- **Theme:** Light / dark / system, persisted in `localStorage`
- **Form memory:** Last user email / display name / org name from `localStorage` (not fake placeholders)
- **Auth:** Access token in memory; refresh via cookie; auto-refresh on app load
- **Phase 3 (shipped):** Chat workspace at `/` — `useSession` REST-first + SSE; Streamdown + `@streamdown/cjk`; live `message.delta`; Agent Mode UI (`agent.progress` trail persisted on user-message `metadata.agent_actions`; brief / `draft.awaiting_image_ok` interrupt; snapshot `interrupted` rehydrates Generate-image CTA); landing recommended-question cards; IG Preview + Confirm; Gemini-style history; **content-based shell** (`split` vs `paged` from pane min-widths, not viewport `lg`); paged Chat primary with history icon + Preview via ready banner / **上一頁**; `llm.failed` inline error + Retry; shell fits `h-dvh` with per-pane scroll; no `useChat`
- **Session client:** `web/src/features/session/` — `api.ts` (REST), `sse.ts` (`@microsoft/fetch-event-source` with Bearer), `use-session.ts` + `session-helpers.ts` + `session-layout.ts`, `session-storage.ts` (per-company last session id), `use-recommended-questions.ts`, `components/chat-panel.tsx` + `session-history.tsx` + `preview-panel.tsx` + `ig-preview-mock.tsx` + `recommended-questions.tsx`
- **Chat persistence:** Backend writes `session_messages` (user always; assistant for `chat` / `ack_confirm` / LLM failure / review exhausted). Agent turns often **do not** append assistant chat rows — brief/draft live in `sessions.state` + `preview_drafts`. **Agent action trail:** after each turn, `agent.progress` payloads are stored on that turn’s **user** message as `metadata.agent_actions` (`[{node, model_tier, model}, …]`); `GET …/messages` returns `metadata` so refresh rebuilds the trail. **Interrupt hydrate:** `sessions.state.awaiting_image_ok` + SSE `session.snapshot.interrupted` (graph `next`) restore the Generate-image card after reopen / API drop. **Hydrate:** `GET /sessions/{id}/messages` + remembered session id in `localStorage`. **History:** split mode left sidebar lists `GET /sessions?company_id=` (pinned group + date groups + search); paged mode opens the same list as a full-page Record view; `PATCH` rename/pin, `DELETE` removes session (+ cascades).

**Run:**

```bash
cd web && pnpm install && pnpm run dev
```

App: http://localhost:5173/login (Vite proxies `/api` → `:8000`; SPA owns `/`, `/login`, `/admin`, …)

---

## Repository Layout (actual)

```
unhinted-marketing/
├── cmd/
│   ├── api/              # FastAPI app; public routes under /api (auth, signals, sessions, admin)
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

**Tests:** `tests/unit` (no DB) · `tests/api` (requires `TEST_DATABASE_URL`) · `cd web && pnpm test` (Vitest Tier 1/2). Policy: [TESTING.md](./TESTING.md).

---

## Environment

| Variable | Purpose |
|----------|---------|
| `TEST_DATABASE_URL` | Isolated Postgres for `pytest tests/api` (skipped if unset) |
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `APP_ENV` | `development` (default) or `production` — production refuses weak JWT |
| `ALLOW_INSECURE_JWT` | Escape hatch for local/tests only (`true` skips JWT secret check) |
| `JWT_SECRET` | Sign access/refresh tokens — **≥32 chars + unique** (prod rejects the published `.env.example` default) |
| `AUTH_RATE_LIMIT_ENABLED` | Rate-limit `/api/auth/register|login|refresh` (default true) |
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
| `LLM_RECORD_ENABLED` | Persist every LLM call to `llm_call_records` (default true; [ADR 0005](./adr/0005-platform-levels-and-llm-records.md)) |
| `QUESTION_CACHE_TTL_HOURS` | Recommended questions cache (default 12) |

**Company profile (JSONB on `entities`):** optional `roast_level` `0`–`3` (default `1`) — see [VOICE.md](./VOICE.md).

See `.env.example`. Local `.env` is gitignored.

---

## Known Gaps / Next Steps

### High-priority risks

| ID | Risk | Status |
|----|------|--------|
| **H1** | Auth rate limit + known-default / weak `JWT_SECRET` | ✅ **Mitigated on this branch** — in-memory limit on register/login/refresh; `APP_ENV=production` refuses insecure JWT |
| **H2** | Interrupt resume ignores user intent (`ainvoke(None)`) | ✅ **Mitigated** — [ADR 0004](./adr/0004-stop-discard-and-image-resume.md): composer lock; Stop discards; `POST /resume-image` only; `/messages` 409 while busy/parked; chat/JSON completions stream + `aclose` on cancel (best-effort upstream abort) |
| **H3** | `use-session.ts` correctness concentrated & untested | ✅ **Mitigated** — pure helpers in `session-helpers.ts` (+ Tier 1 cov gate); `use-session.test.ts` covers restore / send / confirm / SSE merge |
| **I1** | Confirm idempotency key global (cross-user receipt leak) | ✅ **Mitigated** — foreign key → 409; same session/user only replays |

### Other gaps

1. **Phase 3 UI:** Core chat → agent action records (DB-backed on user-message metadata) → preview → confirm stub + history (desktop sidebar / mobile Record–Chat–Preview push pages) shipped. Agent path still rarely writes assistant chat bubbles (brief/preview are side-channel UI). Interrupt Generate-image CTA rehydrates from graph/SSE after fail or refresh.
2. **Phase 2 soft / held:** Image gen via `LLM_IMAGE_MODEL` + MinIO (`S3_*`) when configured; formal curl exit-criteria script still later; `query_market_trends` **schema** landed — adapter wiring still held.
3. **Phase 3 later:** Meta Graph API ingest, BYOK settings page; FB/Threads preview skins. LLM call **records** + admin Trace viewer landed ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md), [ADR 0007](./adr/0007-admin-trace-viewer.md)) — ops guide: [PROMPT_TUNING.md](./PROMPT_TUNING.md). Next: retention/purge policy. `/api` prefix shipped ([ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md)).
4. **Hardening:** ~~Auth rate limits + JWT secret guard~~ + ~~confirm idempotency user/session scope~~; ~~basic API tests~~ + ~~frontend Vitest Tier 1/2~~ + ~~CI~~ ([TESTING.md](./TESTING.md), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)); ~~contracts SSOT~~ ([AGENTS.md](../AGENTS.md), [adr/](./adr/), [contracts/](./contracts/)); ~~mock-LLM graph node tests + CI Tier 1b~~; ~~interrupt Stop / resume-image ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md))~~; ~~persist LLM call records ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md))~~; ~~`/api` path prefix ([ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md))~~; multi-worker SSE + turn-stop registry (Redis) if scaling beyond one API process; media private/signed URLs; re-check org membership on session access after revoke; enable branch protection requiring CI checks; live LLM eval harness later.

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
