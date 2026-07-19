# Unhinted Marketing Agent — Roadmap

> **Stack:** Python (FastAPI) · LangGraph · PostgreSQL (+ pgvector) · React (Tailwind + shadcn/ui)  
> **Market focus (MVP):** Hong Kong hot search & trends  
> **Product model:** Backend autopilot for signals + user-guided session for content → preview → confirm post

---

## Vision

An AI marketing assistant that **continuously scans HK market signals** (Google Trends first; Meta & LIHKG later), surfaces **actionable content recommendations** tied to company profile and personas, and guides users through **iterative preview** until they confirm—at which point posts go out via **traditional platform APIs** (no LLM involved in publish).

---

## Architecture Principles

| Principle | Decision |
|-----------|----------|
| LLM boundary | LangGraph owns **chat → recommend → preview edit loop** only |
| Confirm / publish | **Traditional HTTP handler** — validate token, call platform API, write receipt. Zero LLM. |
| Autopilot vs session | Hot search & question batch = **background workers**; preview = **on-demand session** |
| Grounding | All factual claims cite `source_signal_ids` verifiable in PostgreSQL |
| BYOK | LiteLLM routes cheap models (scan/summary) vs strong models (strategy/critic) |
| Knowledge split | PostgreSQL = operational + graph; OKF = curated news topics + personas (no PII) |
| Preview | **Revision chain** — user can keep requesting edits until satisfied |
| Auth boundary | **JWT access + refresh**; all session APIs require authenticated user; Confirm validates user owns session |

---

## User System & Authentication

### Model

```
users ──< organization_members >── entities (type=company)
  │
  └──< sessions (user_id, company_id)
```

| Table | Purpose |
|-------|---------|
| `users` | Account: email (unique), password_hash, display_name, is_active |
| `organization_members` | Multi-tenant RBAC: user ↔ company entity, role (`owner` \| `admin` \| `member`) |
| `refresh_tokens` | Hashed refresh token family (rotation + revoke on logout) |

**MVP scope:** email/password login; one default company per new user (auto-created `entities` row + `organization_members` as `owner`). OAuth (Google / Meta) deferred to Phase 4.

### API (`/auth/*`)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/auth/register` | Create user + default org; returns tokens |
| POST | `/auth/login` | Email/password → access + refresh JWT |
| POST | `/auth/refresh` | Rotate refresh token; new access token |
| POST | `/auth/logout` | Revoke refresh token family |
| GET | `/auth/me` | Current user + org memberships |

Access token: **15 min** (Bearer header). Refresh token: **7 days** (httpOnly cookie in browser; body for CLI).

### Frontend Login Panel

- Route: `/login` (public) · `/register` (public) · `/` (protected dashboard shell)
- shadcn/ui Card + Form; email/password; error toasts
- Auth context stores access token (memory); refresh via cookie on 401
- Unauthenticated users redirected to `/login`

### Security Defaults

- Passwords: **argon2** via passlib
- JWT signed with `JWT_SECRET` (min 32 bytes in prod)
- Rate limit login/register (Redis or in-memory MVP)
- `sessions.user_id` must match authenticated user on all session endpoints

---

## System Modes (User-Facing)

```
┌─────────────────────────────────────────────────────────────────┐
│  Login / Register                                               │
│  • Email + password · JWT session                               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Landing (Chat Mode)                                            │
│  • Recommended questions (JSON, cached ~12h)                    │
│  • Based on: company profile + hot search + personas            │
│  • User picks a question or free-form chat                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent Mode                                                     │
│  • Text recommendation split into:                              │
│    - can_do[]   (e.g. social post, carousel copy)               │
│    - cannot_do[] (e.g. offline event, brand collab)             │
│  • draft_copy with grounding                                    │
│  • User OK → generate image → enter Preview                     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Preview Mode (iterative)                                       │
│  • Layout: left chat (narrow) · right preview (wide)            │
│  • User keeps requesting edits until satisfied                  │
│  • Each edit → new revision → Critic gate → SSE update          │
│  • Chat "可以出" ≠ publish — UI Confirm button only           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Confirm (NO LangGraph, NO LLM)                                 │
│  POST /sessions/{id}/confirm                                    │
│  • Read latest preview_draft · validate approval_token          │
│  • Platform API (Meta/IG/etc.) · idempotency_key · receipt      │
└─────────────────────────────────────────────────────────────────┘
```

---

## LangGraph Scope

LangGraph implements the **Session LLM Zone** only:

```
nodes:  chat · agent_recommend · classify_intent · edit_copy · gen_image_prompt · critic · ack_confirm
edges:  conditional on critic pass/fail, intent (revise | confirm_intent | chat)
state:  messages, mode, draft, revision, pending_confirm
checkpoint: PostgreSQL (LangGraph checkpointer)

NOT in graph: hot_search_worker · question_generator · POST /confirm · platform adapters
```

---

## Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| API | FastAPI + uvicorn | REST + SSE for preview updates |
| Auth | JWT (python-jose) + argon2 | Access/refresh; httpOnly refresh cookie |
| Workers | Python (`cmd/worker`, `cmd/scheduler`) | ARQ + Redis when provisioned; PG job queue fallback |
| Agent | LangGraph + LiteLLM | Structured output via Pydantic |
| DB | PostgreSQL 16+ | pgvector for signal similarity (MVP) |
| Cache / queue | Redis (optional MVP) | Question cache, job queue, rate limits |
| Media | S3 (Phase 2) | Generated images, OKF bundle archive |
| Frontend | React + Vite + Tailwind + shadcn/ui | Login panel + dashboard |
| Hot search | pytrends / SerpAPI, RSS | LIHKG scrape Phase 2 |

---

## Repository Layout (Target)

```
unhinted-marketing/
├── cmd/
│   ├── api/                 # FastAPI entrypoint (+ /auth routes)
│   ├── worker/              # ARQ / async job consumer
│   └── scheduler/           # Cron: hot_search, question_gen
├── internal/
│   ├── auth/                # JWT, password, deps, refresh tokens
│   ├── perception/          # hot_search, news_scanner, news_promoter
│   ├── session/             # LangGraph graph, nodes, checkpointer
│   ├── reasoning/           # critic, planner (autopilot)
│   ├── tools/               # query_market_trends, publish adapters (stubs → real)
│   ├── memory/              # PG repos, pgvector, OKF reader
│   ├── reliability/         # validator, budget breaker, hallucination check
│   └── llm/                 # LiteLLM router, BYOK config
├── schemas/                 # JSON Schema + Pydantic models
├── migrations/              # PostgreSQL (Alembic)
├── knowledge/               # OKF bundle (news topics + personas)
├── web/                     # React dashboard + login panel
└── docs/
    └── ROADMAP.md           # this file
```

---

## PostgreSQL Schema (Core Tables)

| Table | Purpose |
|-------|---------|
| `users` | Auth accounts (email, password_hash, display_name) |
| `organization_members` | User ↔ company RBAC |
| `refresh_tokens` | Rotating refresh token store (hashed) |
| `raw_news_events` | Every ingested item (url, excerpt, url_hash, signal_id) |
| `entities` | brands, topics, campaigns, personas, **companies** (`okf_path` bridge) |
| `edges` | MENTIONS, AFFECTS, TARGETS, PERFORMED_ON + source_signal_id |
| `campaigns` | Operational campaign state |
| `sessions` | User session state (mode, company_id, **user_id**) |
| `session_messages` | Chat log (left panel) |
| `preview_drafts` | Revision chain (copy, image, platform, approval_token) |
| `tool_receipts` | Idempotent execution receipts |
| `byok_config` | Encrypted provider keys (server-side only) |
| `recommended_questions` | Cached 12h batch JSON |

---

## OKF Knowledge (Hybrid)

**In OKF:** curated news topics, marketing personas (no PII)  
**In PostgreSQL:** raw feeds, operational state, embeddings

```
knowledge/
  index.md
  news/topics/{slug}.md      # promoted when velocity/confidence thresholds met
  personas/{slug}.md         # 3–7 human-authored archetypes, cross-linked to news
```

---

## Hot Search Sources (Phased)

| Phase | Source | Method |
|-------|--------|--------|
| MVP | Google Trends HK | pytrends / SerpAPI |
| MVP | Google News HK RSS | feedparser |
| P2 | LIHKG hot | scrape (Playwright), graceful degrade |
| P3 | Meta trending / insights | Graph API (business account) |

All metrics stored in PG with provenance before LLM reads them.

---

## External Tools (Schema-Validated)

1. **`query_market_trends`** (read-only) — scanning worker, high frequency  
2. **`publish_social_post`** — called only from Confirm handler, not LangGraph  
3. **`launch_ad_campaign`** — Phase 3, requires `approval_token` + atomic budget cap  

---

## Safety (Immutable Policy)

- Max daily ad spend & publish rate limits  
- Topic/region blocklists  
- `approval_token` required per preview revision before Confirm enabled  
- Read-only degradation when Critic confidence below threshold  
- Outbound claims must cite verifiable `source_signal_ids`  
- Session endpoints enforce `user_id` ownership  

---

## Phase Plan

### Phase 0 — Project Bootstrap ✅ (in progress)

- [x] Git repository initialized
- [x] `docs/ROADMAP.md`
- [x] User system design (users, org members, JWT auth)
- [ ] `.env.example` (dev DB at `192.168.5.20:5434`)
- [ ] Python project skeleton (`pyproject.toml`, `cmd/`, `internal/`)
- [ ] Auth API: register, login, refresh, logout, me
- [ ] Alembic migration: `users`, `organization_members`, `refresh_tokens`
- [ ] React login panel (`web/`) — `/login`, `/register`, auth context
- [ ] Minimal README

### Phase 1 — Data & Autopilot Backend

**Goal:** Background ingestion + landing-page question cache; no UI yet (CLI/logs).

- [ ] PostgreSQL migrations: `raw_news_events`, `entities`, `edges`, `recommended_questions`
- [ ] `hot_search_worker` — Google Trends HK + News RSS → PG
- [ ] `question_generator_worker` — company profile + signals → JSON, cache 12h
- [ ] LiteLLM BYOK config loader
- [ ] OKF scaffold: 1 sample news topic + 2 personas + cross-links
- [ ] `news_promoter` worker — threshold → OKF topic markdown

**Exit criteria:** CLI shows top HK signals; cached recommended questions JSON served via API.

### Phase 2 — LangGraph Session + API

**Goal:** Full chat → agent → iterative preview loop; Confirm stubbed.

- [ ] Migrations: `sessions`, `session_messages`, `preview_drafts`
- [ ] LangGraph graph: CHAT → AGENT → PREVIEW (revise loop) + PostgreSQL checkpointer
- [ ] Nodes: `agent_recommend` (can_do / cannot_do), `classify_intent`, `edit_copy`, `critic`
- [ ] FastAPI: `POST /sessions`, `POST /messages`, `GET /events` (SSE)
- [ ] Image generation worker (prompt → asset URL in `preview_drafts`)
- [ ] `POST /sessions/{id}/confirm` — **traditional handler**, stub platform adapter
- [ ] Tool schema validators (Pydantic + JSON Schema) for `query_market_trends`

**Exit criteria:** curl/HTTPie flow from question → draft → 3 revisions → confirm → receipt row.

### Phase 3 — React Dashboard

**Goal:** Observability + session UI; Confirm is a button, not chat.

- [ ] Vite + React + Tailwind + shadcn/ui in `web/`
- [ ] Protected routes; redirect unauthenticated → `/login`
- [ ] Landing: recommended questions cards (poll or SSE refresh)
- [ ] Chat Mode → Agent Mode transition
- [ ] Preview Mode: left chat / right preview (right dominant)
- [ ] Confirm button → calls `/confirm`, shows receipt status
- [ ] BYOK settings page (masked keys, server-side storage)
- [ ] Trace viewer: session messages + revision timeline + signal grounding links

**Exit criteria:** End-to-end demo in browser for one platform (TBD: IG / FB / Threads).

### Phase 4 — Live Publish & HK Sources

- [ ] Real Meta/IG Graph API integration in Confirm handler
- [ ] LIHKG hot scrape worker
- [ ] Budget circuit breaker (atomic PG updates)
- [ ] Redis for queue + question cache (if not already)
- [ ] S3 for media assets
- [ ] OAuth providers (Google) for login

### Phase 5 — Autonomous Extensions (Optional)

- [ ] Full `agent_orchestrator` autopilot loop (Scan → Triage → Plan → Critic → Execute)
- [ ] `launch_ad_campaign` with approval_token
- [ ] OKF Git sync + S3 bundle archive
- [ ] Dedicated vector DB migration path from pgvector

---

## LLM Task Routing

| Task | Model tier | Runs in |
|------|------------|---------|
| Hot search summarize | cheap | worker |
| Recommended questions (12h) | cheap | worker |
| can_do / cannot_do + draft copy | medium | LangGraph |
| Preview edit (copy) | medium | LangGraph |
| Critic / compliance | strong | LangGraph |
| Image prompt | medium | worker |
| **Confirm / publish** | **none** | **API handler** |

---

## Open Decisions

| # | Question | Default if unset |
|---|----------|------------------|
| 1 | Company profile storage | PG JSON column on `entities` (type=company) |
| 2 | First publish platform | Instagram (Meta Graph API) |
| 3 | Image provider | OpenAI DALL-E 3 |
| 4 | Redis in MVP | PG job queue fallback; add Redis when provisioned |
| 5 | LIHKG | Phase 2 (after Google sources stable) |
| 6 | Migration tool | Alembic (Python-native) |
| 7 | Auth provider (MVP) | Email/password JWT; OAuth Phase 4 |

---

## Definition of Done (MVP)

1. HK hot search ingests automatically without user action  
2. Landing shows ≥5 recommended questions refreshed every ~12h  
3. User can **register, login**, and access protected dashboard  
4. User can chat, get can/cannot recommendation, enter preview  
5. User can revise preview unlimited times; each revision Critic-gated  
6. Confirm posts via platform API with idempotency + receipt (no LLM)  
7. All claims traceable to `source_signal_ids` in PostgreSQL  

---

## References

- [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- [LiteLLM](https://docs.litellm.ai/)
- [OKF v0.1](./OKF.md) _(to be written)_
- [API spec](./API.md) _(to be written)_
