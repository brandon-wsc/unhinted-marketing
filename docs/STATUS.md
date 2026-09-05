# Unhinted Marketing — Project Status

> **Last updated:** 2026-09-05  
> **Overall:** Phase 0–1 complete · Phase 2 **soft-complete** (UI-ready) · Phase 3 UI **~80%** · Craft: default HK editor voice + `roast_level` ([VOICE.md](./VOICE.md)) · Company settings Voice + Products + Members + Approvals (K1/K3/K3b/K6) · Preview media append-only ([ADR 0008](./adr/0008-preview-images-append-only.md)) · Security: auth rate limit + confirm user-private idempotency · Observability: LLM call records + platform levels ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)) · Backend pytest ✅ · Frontend Vitest Tier 1/2 ✅ · CI ✅  
> **Dev DB:** `192.168.5.20:5434` / database `unhinted` · **Test DB:** set `TEST_DATABASE_URL` (e.g. `unhinted_test`) for `pytest tests/api`

This document summarizes **what exists today** vs the [ROADMAP](./ROADMAP.md). For architecture and phase plans, see ROADMAP.

---

## Summary

| Area | Status |
|------|--------|
| Auth backend (JWT, register/login) | ✅ Done |
| Auth DB tables + Alembic | ✅ Done |
| React login / register / dashboard shell | ✅ Done |
| i18n (zh-HK, en) | ✅ Done |
| Dark / light theme (manual switch, no system mode) | ✅ Done |
| App header (logo + user menu — dropdown on desktop, dialog on mobile) | ✅ Done |
| HK hot search ingestion | ✅ Done (Google Trends HK only) |
| Recommended questions cache + API | ✅ Done |
| OKF knowledge scaffold | ➖ Removed — knowledge in PostgreSQL only |
| Company settings (Voice + Products + Members + Approvals) | ✅ K1 / K3 / K3b / org team / K6 — `/settings` |
| LangGraph session / preview / confirm API | ✅ Soft-complete — enough for Phase 3 UI |
| Chat UI shell (`useSession` + Streamdown) | ✅ Done |
| Chat token stream (`message.delta`) | ✅ Done — live deltas via SSE, batched in node |
| Agent Mode UI (`agent.progress` + cards) | ✅ Done — action trail persisted on user-message metadata; in-flight header `幫緊你幫緊你` / `Working` (no live seconds, chevron stays clickable); done header `做咗x秒` / `Worked for`; interrupt CTA survives fail / refresh |
| Landing recommended-question cards | ✅ Done — empty-state cards → `sendMessage` |
| Preview Mode (IG mock + draft editor) | ✅ Done — Edit Copy / Edit Image dialogs; multi-image carousel; mobile push pages; Confirm auto-flush |
| Manual draft API `POST …/draft` | ✅ Done — no LLM; revision + approval_token |
| Confirm UI → stub `/confirm` | ✅ Done — published / failed / stubbed receipts; copy-only Confirm gate |
| Chat history (hydrate + Gemini sidebar) | ✅ Done — list / pin / rename / delete; desktop sidebar + mobile record page |
| pgvector on dev DB | ✅ Done (PG 18.4 · `pgvector/pgvector:pg18`; enable with `CREATE EXTENSION vector`) |

**Decision (2026-09-02) — Real publish: Instagram adapter + org social accounts:** → [ADR 0022](./adr/0022-real-publish-instagram.md) · plan: [PUBLISH_PLAN.md](./PUBLISH_PLAN.md)
**Update (2026-09-05) — Meta OAuth connect added:** editor `/settings?tab=instagram` now connects via Meta OAuth (popup + poll); manual token paste removed. Callback URL for the Meta App Dashboard → `META_OAUTH_REDIRECT_URI`.

- **Backend shipped** — `social_accounts` + editor HTTP (`GET/PUT/DELETE …/social-accounts`) + `connect-social-account` CLI; Confirm dispatches on `PUBLISH_ADAPTER` (default `stub`); `session.snapshot` hydrates the latest confirm receipt
- **UI shipped** — preview receipts (`published` / `failed` / `stubbed`) + copy-only Confirm gate; editor-only `/settings?tab=instagram` (last4 only, never the raw token)
- **`social_accounts` table** — org-scoped IG credentials, Fernet-encrypted (reuses `BYOK_ENCRYPTION_KEY` + `byok_providers` shape)
- **Meta OAuth (2026-09-05)** — PKCE auth-code flow via Meta dialog; encrypted connect-state + CSRF on the `social_accounts` row; public `/api/social/oauth/callback` recovery of the org from `state`; token + `ig_user_id` upserted server-side. Env: `META_APP_ID`, `META_APP_SECRET`, `META_OAUTH_REDIRECT_URI`, `META_OAUTH_SUCCESS_URL`. CLI/PUT seeding still available as fallback.
- **`PUBLISH_ADAPTER=stub|instagram`** — adapter in `internal/tools/publish.py`; IG two-phase container → media_publish
- **Copy-only drafts rejected at Confirm** (`400 image_required`); missing IG account → `400 social_account_not_connected`; receipt `stubbed` / `published` / `failed` with optional `permalink` / `error_kind`; failed publish does **not** set `session.status=confirmed`
- **Boundaries unchanged** — Confirm-only publish ([ADR 0003](./adr/0003-confirm-without-llm.md)); per-revision `approval_token`; user/session-scoped idempotency

**Decision (2026-08-31) — Native Gemini + Vertex Express BYOK:** → [ADR 0021](./adr/0021-org-byok-native-gemini.md)

- **Native `provider_type` only when the wire is not Chat Completions + Images.** Enum is `openai` \| `anthropic` \| `openai_compatible` \| `gemini` \| `vertex_ai`. Clones stay `openai_compatible` (DeepSeek, OpenRouter, Groq, …). Vertex **OAuth** / Bedrock / Cohere / Ollama-native / Azure-as-type deferred
- **Gemini = AI Studio API key** — harness `GoogleModel` + `GoogleProvider`; LiteLLM `gemini/` prefix; model list `GET …/v1beta/models` + `x-goog-api-key`; image slot via `aimage_generation` with inline-b64 normalize. Env `GEMINI_API_KEY`
- **Vertex Express = API key only** — distinct type (`vertex_ai`); harness `GoogleCloudProvider(api_key=…)`; `genai.Client(vertexai=True, api_key=…)` for JSON/text/stream/image (not LiteLLM). Probe is `POST …:generateContent?key=` (Express has no ListModels). Env `VERTEX_AI_API_KEY` or `GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI=true` (never treat `GEMINI_API_KEY` as Express; never set the flag in-process)

**Decision (2026-08-30) — Org BYOK: keys / model registry / per-tier routing:** → [ADR 0020](./adr/0020-org-byok-keys-models-routing.md) · plan: [BYOK_PLAN.md](./BYOK_PLAN.md) · native Gemini + Vertex Express: [ADR 0021](./adr/0021-org-byok-native-gemini.md)

- **Three decoupled layers** — `byok_providers` (Fernet-encrypted keys) / `byok_models` (registry, `chat|image` capability) / `byok_routing` (fixed `cheap/medium/strong/image` FK slots); one model can serve multiple slots. Supersedes ROADMAP's single `byok_config` table
- **One resolver, both LLM paths** — `resolve_llm_model(company_id, tier)` scoped per turn via contextvar; LiteLLM router passes per-call kwargs (no more global mutation on the org path); Pydantic AI harness consumes the same resolution; env behavior bit-identical when no org rows exist
- **Env keys stay as per-slot platform fallback** — NULL slot → platform key for that tier; dev/eval/onboarding unchanged
- **Editor-only** (owner/admin); **two-phase delete** (409 + dependents → `?force=true` cascade); **hybrid model-id fetch** (provider list proxy + `openai`/`openai_compatible` `{base}/images/models` merge; capability from modality metadata; typed id valid if unlisted; inference fallback); **SSRF guard** on user-supplied base URLs; **per-provider-row model-list cache**; **background auto-probe after save**; **add-model dedupe attaches**
- **Settings UI** — editor-only `?tab=models` (old `?tab=api-keys` rewrites). Three unmixed surfaces, no wizard. Add key (Keys heading, key-only dialog) and Add model (Models heading, searchable model-id combobox) each save-and-close; neither offers the next layer. Add model is disabled until a key exists and never creates a key. Routing is the four slot dropdowns on the page — the only place slots are assigned. Credential dialogs do not dismiss on overlay click; their errors render inside the dialog.
- **Slot capability match is app-level** (`PUT /routing` + resolver skip-to-env); enum columns + `openai_compatible` requires `api_base` are CHECK-constrained (`gemini` / `vertex_ai` added in [ADR 0021](./adr/0021-org-byok-native-gemini.md)). Models have no `created_by`/`updated_by`; routing has no `created_at` (intentional)
- **API surface premise** — Chat Completions + Images for `openai` / `anthropic` / `openai_compatible`; `litellm.drop_params = True` is the compatibility backstop and must not be removed; native Gemini + Vertex Express are the Completions exceptions ([ADR 0021](./adr/0021-org-byok-native-gemini.md)); Responses API adoption is a separate future ADR

**Decision (2026-08-19) — Queue send while turn in-flight:** → [ADR 0016](./adr/0016-queue-send-while-turn-in-flight.md) (supersedes ADR 0004 composer lock). Composer stays open; Send enqueues in the SPA (max 3); Stop discards the running turn only; drain after idle unless parked at image OK.

**Decision (2026-08-23) — Session switch isolation + composer drafts:** Leave ≠ Stop. In-flight REST apply / `sending` / agent trail are bound to the session on screen. Queue + textarea (incl. mid-edit) save/restore per session in SPA memory; still lost on refresh.

**Decision (2026-08-24) — Session fork (Gemini-style):** → [ADR 0017](./adr/0017-session-fork.md)

- **`POST /api/sessions/{id}/fork`** — copies messages up to the forked assistant message + preview draft/media **as of the fork-point message** (time-aligned by `created_at`; later edits / later-created previews don't travel) into a new session; **fresh `approval_token`** minted (never shared); fork starts `active`, unpinned; `preview_note` in the response flags surprising outcomes (`carried_stale` / `not_carried_later`) for an info toast
- **Lineage** — `sessions.forked_from_session_id` / `forked_from_message_id` / `forked_from_title` snapshot; `GET …/messages` returns session `forked_from` + per-message `forks[]`
- **Naming** — `"(n) base"`, `n` = forks of the direct source + 1, existing `"(n) "` prefix stripped
- **UI** — fork button on assistant messages (copy → fork → time); new chat divider "Forked from {source}"; source message chip "Forked to {title}" / "Forked to {n} chats" → jump menu

**Decision (2026-08-24) — Recommended questions worker graph + fill:** → [ADR 0018](./adr/0018-recommended-questions-worker-graph.md)

- **Not the session graph** — dedicated worker LangGraph; must not `start` / Confirm / upsert org catalog. Clicking a card stays `sendMessage` (optional `source_question_id` handoff warms first-turn research)
- **GET miss fills** — no row: start or join per-company run as a background task, answer **202 generating immediately** (`run_id` + `status`; no in-request wait; join = poll `question_runs` in PG, multi-worker safe); last run `failed` → 202 `status: failed` for a retry CTA. Expired cache stays 200 + `is_stale` (no auto-run, no landing refresh). **POST `…/recommended-questions/refresh`** is the empty-state retry after `failed` (and CLI `--force`); scheduler does routine replacement. GET 200 adds `run_status` (`idle` / `running` / `failed`). A `running` row with no live worker (uvicorn reload / crash) is **abandoned** instead of joined. Cache TTL (13h) outlives the 12h tick
- **Pipeline** — `ensure_signals` → `cheap_screen` → `shallow_research` → `filter` → `deep_research` → `product_match` (read-only) → `compose_questions` (voice + roast, real signal refs, text + trend-combo dedupe vs last N days). Timing corpus is **Trends + RSS only** (Tavily still persists for research, but is not next-run recency fuel). `cheap_screen` cluster-caps one topic per IP/entity and does **not** recency-top-up rejected citywide trends. An empty LLM `keep` (or zero keyword overlap) falls back to a cluster-capped corpus slice (`screen_empty_fallback`) instead of wiping the shortlist. `filter` drops no-bridge Latin-IP / celebrity-gossip titles unless the fingerprint matches. Cold-start ladder unchanged (fingerprint → `profile.inferred_category` → diversity fallback, also cluster-capped). **Compose voice ≠ topic gravity** — civic/weather signals stay; questions stay 輕鬆小編 (scene + 出 post), not 時事／政策評論. `deep_research` scene/emotion/products are passed into compose.
- **Trace** — `question_runs` (status `running|succeeded|failed`) + `question_node_steps`; do not overload Session Trace; admin run list aggregates per-run tokens/cost from `llm_call_records`

**Decision (2026-08-29) — Pydantic AI inner harness; graph narrows to mode/lifecycle:** → [ADR 0019](./adr/0019-pydantic-ai-inner-harness.md)

- **Buy the inner loop, keep the graph** — node-internal LLM calls that need a tool loop (chat / research / execute) adopt Pydantic AI (narrow per-stage agents, `output_type` on `schemas/` models, LiteLLM BYOK unchanged); LangGraph is narrowed but **kept** for mode routing, checkpointer, image interrupt, turn lifecycle. Grounding / reviewer stay single-shot
- **Boundaries unchanged** — Confirm / publish / catalog upsert stay HTTP and are never registered as tools; approval stays outside the loop (v1: no harness tool-approval — all in-loop tools are read-only; future gated tool → park → HTTP approve/deny → resume, zero-LLM decision path); documents (later) are `attachment_id` tools returning slices, full text into the existing PG ingest plane
- **Chat spike on this change set** — `chat` node only; validates SSE event mapping (dedupe unchanged), Stop → `aclose` teardown, `TestModel` CI with no live key, allowlist isolation. This ADR locks direction, not a two-PR split
- **Chat `llm_call_records`** — harness wraps `recorder.track` (`kind=chat_text`); one row per chat turn (tool-loop usage aggregated). Correlation still `call_context(node:chat)`
- **Research `query_generator` inner harness** — Pydantic AI agent (`output_type=QueryGenOut`, tools `ingest_web_search` / `query_market_trends`); `research_ingest` still PG persist (agent only calls the existing Tavily∪PG adapter) and skips Tavily when the agent already ingested. Recorder `kind=chat_json`, caller still `node:query_generator`. Graph vertices unchanged.
- **Execute `executor_post` inner harness** — Pydantic AI agent (`output_type=DraftOut`, tool `query_market_trends` only); typed draft only — publish / Confirm stay HTTP. Recorder `kind=chat_json`, caller still `node:executor_post`. Graph vertices unchanged.
- **Revise `edit_copy` inner harness** — Pydantic AI agent (`output_type=EditOut`, tool `query_market_trends` only); typed draft only — publish / Confirm stay HTTP. Recorder `kind=chat_json`, caller still `node:edit_copy`. Graph vertices unchanged.

**Decision (2026-08-08) — Chat research gate + Tavily∪PG:** → [ADR 0009](./adr/0009-research-gate-and-tavily-ingest.md)

- **Unified `route_intent`** — one structured call: `graph_intent` + `research` (`need_facts` / `ambiguous` / `ask_clarify` / `entity_surface`); no separate graph-routing classifier
- **`fast_rule_checker`** — semantic-router + FastEmbed (multilingual MiniLM; e5-small not in FastEmbed registry) with regex fallback; only `need_search` → `research_rule_pass`. Cold encoder load is **background** (API lifespan + first classify); a turn never waits on download. Until the router is ready, the gate uses regex. Chat shows optimistic `route_intent` progress — do not surface “downloading embedding” or `fast_rule_checker` / `persist_preview` in the action trail.
- **`query_generator`** — 1–3 atomic `search_queries` (**one conjunct each** — do not glue `Usagi rabbit food`); follow-up sense-picks rewrite from `recent_thread` so the **set** keeps the prior intent **and** the new sense (do not cheap-path `Chiikawa` → `Chiikawa Hong Kong`, which drops 兔糧); JP entity queries (e.g. `ちいかわ うさぎ`) are OK alongside English food/feed queries; reject spoken clauses and mixed Latin+CJK entity pastes; gloss fallback splits entity vs `兔糧` → `rabbit food` when LLM unavailable
- **Both sources** — research always uses PostgreSQL **and** Tavily; do not skip Tavily on PG hit; both land in `raw_news_events`
- **Act ≠ search** — `start` / revise gated on clear intent (+ clarify if ambiguous), not on Tavily success; **ambiguity does not block research** — searchable phrases search best-effort first; ask_clarify is for drafting, not a quiz instead of search
- **Search ≠ trusted** — soft-fail continues the turn; `research.query_source` (`llm` / `normalize` / `fallback`) + `research.signals_trusted` mark quality for chat/draft/reviewer. Gloss+Tavily still run on parse miss; untrusted signals must not be led as current facts. Reviewer parse miss is fail-closed.
- **Admin** — `GET /api/admin/sessions/{id}/research` + `/admin` Research tab
- **Implementation** — shipped on `feat/session-research-tavily` (`TAVILY_API_KEY`, semantic-router, nodes, admin)

**Decision (2026-08-04) — Default HK social craft + roast_level:** → [VOICE.md](./VOICE.md)

- **Default craft** — HK editor voice (IKEA feel × Duolingo short/sharp): 貼地 · 有鉤 · 有畫面 · 短 · 有邊界
- **Tunable** — `entities.profile.roast_level` 0–3 (missing → 1); injected as `company_context.voice` in `load_context`
- **Prompts** — `BRAINSTORM` / `EXECUTOR_POST` / `EDIT_COPY` / `REVIEWER` share craft block + few-shots; chat stays assistant voice

**Decision (2026-08-22) — zh-HK Traditional Chinese voice (no `yue` locale):** → [VOICE.md](./VOICE.md)

- **Locale** — UI + draft locale is `zh-HK` 繁體中文（香港）only (+ `en`). Do not ship a separate 廣東話 / `yue` catalog.
- **Register** — spoken HK phrasing, 港式英文, and 標語文言 are **voice layers** inside `zh-HK`, not a second language picker.
- **UI copy** — `zh-HK.json` uses that spoken register (chat empty states, tagline); errors / legal stay clear.

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

**Decision (2026-08-02) — Contracts SSOT entry:** `AGENTS.md` + [ADRs](./adr/) + `schemas/contracts.py` / `schemas/tools.py` + generated `docs/contracts/` + `docs/openapi.json`; FE session types mirror in `web/src/features/session/generated/` via `scripts/typescript_gen`. REST > SSE locked in [ADR 0002](./adr/0002-rest-source-of-truth-sse-enhancement.md); Confirm without LLM in [ADR 0003](./adr/0003-confirm-without-llm.md).

**Decision (2026-08-02) — Graph mock-LLM CI:** Session node unit tests monkeypatch LLM/repos (no API key on GitHub). Opt-in `node_trace_recording()` for step I/O. CI Tier 1b ≥70% on `nodes` + `trace`. Live LLM eval is on-demand (`python -m scripts.eval_agent`), not a PR job and not a nightly gate.

**Decision (2026-08-03) — Platform levels + LLM call records:** → [ADR 0005](./adr/0005-platform-levels-and-llm-records.md)

- **Platform privilege** — numeric `users.platform_level` ladder 0–10 with named rungs + gaps (`MEMBER`=3 default, `ADMIN`=6 read-only records, `SUPERADMIN`=9 full); threshold checks via `require_platform_level`; tenant `organization_members.role` stays separate
- **Bootstrap** — CLI only: `python -m cmd.worker set-platform-role --email … --level superadmin`
- **LLM call records** — every provider call (10 session LLM nodes + `question_generator` worker) persisted to `llm_call_records` with prompts, response, tokens, latency, status, `parse_ok` / `fallback_used`; instrumented at the `internal/llm/router.py` choke point; correlation via contextvars; toggle `LLM_RECORD_ENABLED` (default on)
- **Platform ops surface** — `GET /api/admin/llm-calls` (+ `/{id}`), `GET /api/admin/node-steps` (+ `/{id}`), `GET /api/admin/sessions/{id}/trace`, `GET /api/admin/sessions/{id}/research` gated by `require_platform_level(ADMIN)`; web **System** at `/system` (UserMenu, level ≥ 6) with tabs: LLM calls | Node steps | Research | Session Trace ([ADR 0007](./adr/0007-admin-trace-viewer.md)). **API path stays `/api/admin/*`** (platform namespace, not tenant admin); SPA `/admin` redirects to `/system` — see decision 2026-08-13 below.

**Decision (2026-08-03) — API `/api` prefix vs SPA proxy collision:** → [ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md)

- Same-origin vite proxy + top-level API paths (`/admin`, `/sessions`, …) was a **latent namespace footgun**; became user-visible when SPA `/admin` shared a prefix with the API (refresh → FastAPI `{"detail":"Not Found"}`)
- **Executed 2026-08-04:** all public HTTP routes under `/api/…`; vite single proxy `/api` → API; SPA document routes (`/`, `/login`, `/system`, …) no longer collide with API prefixes

**Decision (2026-08-13) — SPA “System” vs API `/api/admin/*` (intentional split):**

- **User-facing** — UserMenu **System** → SPA `/system` (platform ops: LLM trace, research). Legacy `/admin` → redirect `/system` (preserve query).
- **HTTP API** — **unchanged** `/api/admin/*`; `admin` here means **platform-level** routes ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)), **not** company `organization_members.role` admin/owner.
- **Tenant admin** — Company settings (`/settings`): voice, products, members — separate namespace entirely.
- **Not renaming API to `/api/system`** in this slice — avoids breaking churn; UI label and API path may differ (documented; optional `/api/platform/*` migration later).

**Decision (2026-08-03) — Admin Trace viewer:** → [ADR 0007](./adr/0007-admin-trace-viewer.md)

- Production `session_node_steps` + `turn_id` correlation with `llm_call_records`; admin tabs Node steps / Session Trace

**Decision (2026-08-06) — Frontend UI system (tokens + shadcn layers):**

- **Primitives** — `web/src/components/ui/*` is the only control stack (shadcn); compose in `components/` / `features/`; no parallel Button/Input/Dialog
- **Tokens** — Prefer semantic utilities (`bg-card`, `text-muted-foreground`, …) from `web/src/index.css` `@theme`; avoid `var(--color-*)` in JSX classNames
- **Session shell layout** — `split` vs `paged` from **container width vs content min-widths** (`session-layout.ts`: history + chat [+ preview]), not viewport `lg` / device names; measured via `useContainerWidth` on the chat shell. Split + preview: leftover after history is resizable (default chat 40% / preview 60%, both mins 360px bind; ratio persisted in `localStorage`). Paged remains the overflow valve. **Held:** chat/preview order swap.
- **Agent rule** — [`AGENTS.md`](../AGENTS.md) (Web UI system)
- **Composed helpers** — `FormField`, `IconButton` in `web/src/components/`; menus/confirm via `DropdownMenu` / `AlertDialog`

**Decision (2026-08-09) — Design-in-repo docs first (harness desk proposed, CSS unchanged):**

- Positioning + token proposal under [`docs/design/`](./design/) — reliable shell harnesses unhinged craft; see [BRIEF](./design/BRIEF.md) / [TOKENS](./design/TOKENS.md)
- No Liquid Glass / neon shell; structure stays shadcn

**Decision (2026-08-16) — Portable agent instructions (no harness lock-in):**

- Execution rules (commits, Alembic, web UI) live in [`AGENTS.md`](../AGENTS.md). Nested [`web/AGENTS.md`](../web/AGENTS.md) / [`migrations/AGENTS.md`](../migrations/AGENTS.md) only point back; they are not a second copy.
- Do not keep a parallel copy in harness-specific files (`.cursor/rules/*.mdc`, `CLAUDE.md`, …). Personal tool prefs stay in the operator's home directory, not this repo.

**Decision (2026-08-10) — Harness desk applied to runtime + chrome refresh:**

- `web/src/index.css` carries the harness desk tokens (IBM Plex Sans / Noto Sans HK, ink primary, voice accent); Inter + indigo removed
- Voice accent (`text-voice` / `bg-voice` / `bg-voice-soft` / `border-voice-border`) — craft copy **and** interaction chrome; see 2026-08-20 below. Confirm / primary stay ink.
- **Theme is manual light/dark only** — no system mode; single `UserMenu` module renders a dropdown on desktop and the whole menu as a dialog on mobile
- Composer send/stop are ghost icon buttons (akar send mark; lucide square stop)
- Focus rings standardized to 1px solid `ring` across input / textarea / select / badge / scroll-area
- App header spreads full width (logo hard-left, user menu hard-right) — no centered `max-w-5xl` column

**Decision (2026-08-20) — Voice is the interaction pulse:**

- `ring` aliases `voice` (field / keyboard focus) — not `info` blue. `info` stays status alerts only.
- `accent` / `accent-foreground` alias `voice-soft` / `voice` — hover, selected, queued, ghost/outline button hover.
- `secondary` stays the 6% ink|white **resting** wash (tabs track, read-only, notes).
- Field hover → `border-voice-border`; focus → `ring` / `border-voice`. Queued composer stack → `bg-card` + `border-voice-border` (tuck + icon); row hover → `bg-accent` + `text-accent-foreground`. Do not fill the stack with `voice-soft` (no darker hover stop).
- Composer card stacks textarea then send/stop row below it (not overlaid on the textarea corner); queue tucks above the card ([ADR 0016](./adr/0016-queue-send-while-turn-in-flight.md)).
- Primary / Confirm stay ink. Do not paint solid `bg-voice` on shell chrome.

**Decision (2026-08-10) — Company settings Voice + Products (knowledge K1/K3/K3b):**

- Spec: [`docs/knowledge/`](./knowledge/) (MODEL / SESSION / COLLECT / UI); cover rules locked in COLLECT §2
- **Voice** — `GET/PATCH /api/companies/{id}/voice`; owner/admin edit; persists `roast_level` / locale / forbidden / tone into `entities.profile`
- **Products** — Alembic `1f96a702125c` `products` table; CSV/xlsx import + Mine Add row (optional notes); org covers user on SKU clash for retrieve
- **UI** — UserMenu → Company settings (`/settings`); tabs Voice · Products (Org | Mine) · Members · **Approvals** (owner/admin)
- **K6** — Mine propose → Approvals approve/reject; proposer can cancel pending ([ADR 0011](./adr/0011-knowledge-commit-without-llm.md)); chat scratch still not org KB
- **K1 slim (2026-08-10):** `load_context` → top-level `voice_pack` + `audience_catalog`; LLM nodes get identity-only `company` (no raw `profile` / `personas[]`)
- **K2 (2026-08-10):** `trend_searcher` → top-level `ranked_signals` + `trend_notes` (no longer nested under `company_context`)
- **product_matcher (2026-08-10):** SQL Tier A/B retrieve, org-wins SKU cover; `product_clarify` → chat; primary product into brainstormer / executor / grounding
- **K4 (2026-08-10):** `products.embedding` (pgvector 384) + FastEmbed hybrid retrieve; cross-tenant retrieve test
- **K5 (2026-08-10):** `exemplar_captions` on Voice settings + Confirm promote (`POST …/voice/exemplars`); into `voice_pack`

**Decision (2026-08-11) — Org membership, invites, shared-asset scope:** → [ADR 0010](./adr/0010-org-membership-invites-and-shared-assets.md)

- **Members API** — ✅ `GET/PATCH/DELETE …/members`, `PATCH /api/companies/{id}` rename; sole-owner rules enforced
- **Invites API** — ✅ `POST/GET/DELETE …/invites`, `GET /api/invites/{token}` preview (`email` + `company_name`, [ADR 0014](./adr/0014-invite-public-preview.md)), `POST /api/invites/{token}/accept`; `internal/notify/` (`link` / `smtp` / `console`); invite create rate-limited
- **Team UI** — ✅ Members tab, `/invite/:token`, login `next`; bootstrap solo-org replace on accept ([ADR 0013](./adr/0013-invite-accept-replaces-bootstrap-org.md)); teammate session isolation in `tests/api/test_session_isolation.py` (CI `backend-api`)
- **Email pluggable** — `EMAIL_BACKEND` = `link` (default) / `smtp` / `console`; `WEB_BASE_URL` required for link building; `internal/notify/` seam
- **MVP one user ↔ one org** — invite accept **409** if already in a real team; **bootstrap solo-org is replaced** ([ADR 0013](./adr/0013-invite-accept-replaces-bootstrap-org.md)); products rehome to Mine, voice discarded ([ADR 0015](./adr/0015-invite-rehome-solo-products.md)); no switcher
- **Shared = products + voice only** — sessions/media/drafts stay user-private; revoke cuts company access immediately (per-request membership); confirm stays open to all members (publish-role gate is not part of K6; still [ADR 0010](./adr/0010-org-membership-invites-and-shared-assets.md))
- **Unblocks K6** promote-to-org Approvals — **shipped** ([ADR 0011](./adr/0011-knowledge-commit-without-llm.md))

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
| Automated tests | ✅ Backend + FE Tier 1/2 + CI + on-demand live eval | BE: `tests/unit` + `tests/api` (`TEST_DATABASE_URL`). FE: `cd web && pnpm test` (Vitest + RTL — lib utils + `session-helpers` / `session-layout` / `useSession` + PasswordBox / UserMenuDropdown). Live LLM: `python -m scripts.eval_agent` (not CI). Policy [TESTING.md](./TESTING.md). CI: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

### Phase 1 — Data & Autopilot Backend · **100%**

| Item | Status | Notes |
|------|--------|-------|
| Alembic `5dae474953cd` (signals) | ✅ | `raw_news_events`, `edges`, `recommended_questions` |
| Hot search worker | ✅ | `python -m cmd.worker hot-search` (Google Trends HK + RSS news) |
| Question generator | ✅ | Worker LangGraph (ADR 0018); 13h cache; GET-miss fill; RSS + Trends ingest |
| News promoter | ✅ | Top trends → topic `entities` + `edges` in PG |
| LiteLLM BYOK loader | ✅ | Env-based (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `VERTEX_AI_API_KEY` or `GOOGLE_API_KEY`+`GOOGLE_GENAI_USE_VERTEXAI`, model tiers); `LLM_API_BASE` → `openai/` prefix; native Gemini → `gemini/`; Vertex Express → google-genai `vertexai=True` ([ADR 0021](./adr/0021-org-byok-native-gemini.md)) |
| Default personas | ✅ | Seeded in `entities` (type=persona) on first question run |
| Signals API | ✅ | `GET /api/signals/top` |
| Questions API | ✅ | `GET /api/companies/{id}/recommended-questions` (200 cache / 202 fill); `POST …/refresh` |
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
| Chat research + Tavily ingest | ✅ | ADR 0009; semantic gate + multi-query + gloss; Tavily adapter; admin Research tab; `TAVILY_API_KEY` for live search |
| Curl exit-criteria script | ⏸ **Held** | Manual/API path works; formal curl checklist later |

**Held Phase 2 work does not block Phase 3 UI.**

### Phase 3 — React Dashboard + Meta Signals · **~80% · IN PROGRESS**

**Focus now:** Meta ingest / BYOK / Trace (core session UI shipped — chat → agent → preview → confirm + history).

| Item | Status | Notes |
|------|--------|-------|
| Auth pages + protected shell | ✅ | Login / register; `/` is now the chat workspace |
| Chat UI shell | ✅ | `web/src/features/session/` — `useSession` + message list / composer; Streamdown + `@streamdown/cjk`; Vite proxies `/api` → API |
| Chat token stream (`message.delta`) | ✅ | `chat` node streams LiteLLM → batched live deltas via event bus; first message waits for SSE open before POST |
| Agent Mode UI | ✅ | `agent.progress` live inside each graph node; Cursor-style action-record trail persisted on the triggering user row as `session_messages.metadata.agent_actions` (hydrate on reopen) plus turn `duration_ms`. In-flight header is `幫緊你幫緊你` / `Working` (no ticking seconds; chevron stays enabled). Completed header is `做咗x秒` / `Worked for`. Node labels: running present-tense + `…`, done past tense. Optimistic `route_intent` while POST/SSE catch up; hide `fast_rule_checker` / `persist_preview`; brief card + interrupt card (`draft.awaiting_image_ok` / snapshot `interrupted`); resume via `POST /resume-image`; composer open while in-flight with FE send queue (max 3) and Stop beside Send ([ADR 0016](./adr/0016-queue-send-while-turn-in-flight.md)); Stop mid-image re-parks Generate-image CTA; Stop while parked discards turn ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md)) |
| Landing: recommended questions cards | ✅ | Empty-state cards from `GET /api/companies/{id}/recommended-questions`; 202 poll on miss; click → `sendMessage` (+ optional `source_question_id`); failed empty → POST refresh retry; scheduler replaces cache |
| Preview Mode (left chat / right preview) | ✅ | Split: IG mock + **Edit Copy dialog** + multi-image carousel; **hover/tap image → Edit image**; chat|preview leftover-relative **resizable**. Paged: Preview push page with **上一頁** (content-width shell, not `lg`) |
| Confirm button → `/confirm` | ✅ | Dirty auto-flush → draft then confirm; stub receipt in panel |
| Manual draft API `POST …/draft` | ✅ | No LLM; bump revision + `approval_token`; caption-only reuses `media_ids` ([ADR 0008](./adr/0008-preview-images-append-only.md)) |
| Preview media APIs | ✅ | `GET/POST …/media`, `PATCH …/media/{id}/plan`, `POST …/media/{id}/regen`, `POST …/media/{id}/remove`, `POST …/media/{id}/upload` — append-only image rows + new draft |
| Chat history hydrate + list | ✅ | `GET /api/sessions`, `GET …/messages`, `PATCH/DELETE …/{id}` (`title`/`pinned`); localStorage last session; desktop Gemini-style sidebar; mobile Record page (history icon → full list; **上一頁** back to Chat). **History search:** `GET /api/sessions?q=` matches everything user-visible — title, message content, brief + current draft (`sessions.state`), all draft revisions (`preview_drafts.copy`) — server-side (ILIKE, user-scoped, flat newest-first) with `matched_snippet` (message → brief → draft fallback); sidebar search box debounces into it (search mode replaces pinned/date groups; clear restores browse list) |
| LLM call records + System page | ✅ | [ADR 0005](./adr/0005-platform-levels-and-llm-records.md) — `llm_call_records` + platform levels; `/api/admin/llm-calls` API + web `/system` |
| API `/api` path prefix | ✅ | [ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md) — hard cut; SPA `/system` (legacy `/admin` redirect) |
| Admin Trace viewer (node-steps + session) | ✅ | [ADR 0007](./adr/0007-admin-trace-viewer.md) — `session_node_steps` + `turn_id`; admin tabs Node steps / Session Trace |
| Meta Graph API hot search | ⏸ | Next after core UI |
| BYOK settings page | ✅ | Editor-only keys / models / routing tab ([ADR 0020](./adr/0020-org-byok-keys-models-routing.md), native Gemini + Vertex Express [ADR 0021](./adr/0021-org-byok-native-gemini.md)) |
| Trace viewer | ✅ | Admin Session Trace tab ([ADR 0007](./adr/0007-admin-trace-viewer.md)) — not end-user UI |

---

## What Works Today

### Backend (`cmd/api`)

- **Health:** `GET /api/health` → `{"status":"ok"}`
- **Auth:** Full email/password flow with JWT access token (15 min) + refresh token (7 days, httpOnly cookie on `/api/auth`)
- **Signals:** `GET /api/signals/top` — latest HK market signals from PostgreSQL
- **Questions:** `GET /api/companies/{id}/recommended-questions` — 200 cache / 202 generating (ADR 0018 fill); `POST …/refresh` failed-empty retry (CLI `--force` / scheduler for routine fill)

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
| `raw_news_events` | Ingested HK signals (Google Trends HK + RSS news; Meta API later in Phase 3) |
| `edges` | Graph links (signal → topic entities) |
| `recommended_questions` | 13h cached landing question JSON |
| `question_runs` | Worker graph run status (ADR 0018) |
| `question_node_steps` | Per-node I/O for question runs |
| `sessions` | Chat session (mode, user_id, company_id, title, pinned, state JSONB) |
| `session_messages` | Chat log (user always; assistant for chat / ack / LLM errors — not every Agent node) |
| `preview_drafts` | Revision chain + approval_token + `media_ids` |
| `preview_images` | Append-only image versions (url + plan) ([ADR 0008](./adr/0008-preview-images-append-only.md)) |
| `tool_receipts` | Idempotent Confirm / tool receipts |
| `llm_call_records` | Per-call LLM record: correlation, prompts, response, tokens, latency, status, `parse_ok`/`fallback_used` ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md)) |
| `products` | Org / user product catalog (`owner_scope`, `sku`, `search_document`, `profile` JSONB, `embedding vector(384)`) — Alembic `1f96a702125c` + `12d5c92e3f74` |
| LangGraph checkpoint tables | Owned by `AsyncPostgresSaver.setup()` (not Alembic) |

**pgvector:** Dev DB on Synology NAS runs **`pgvector/pgvector:pg18`** (PostgreSQL **18.4**). PG 18+ Docker images mount data at **`/var/lib/postgresql`** (not `/var/lib/postgresql/data`). After restore/migrate, run `CREATE EXTENSION vector;` on `unhinted`.

### Frontend (`web/`)

| Route | Description |
|-------|-------------|
| `/login` | Email/password login |
| `/register` | Sign up + default workspace |
| `/` | Protected **chat workspace** — split: history + chat (+ preview); paged: Record / Chat / Preview |
| `/settings` | Company settings — Voice · Products (Org \| Mine) · Members · Approvals |
| `/invite/:token` | Invite accept (public page; POST accept requires auth) |
| `/system` | Platform ops (level ≥ 6) — LLM calls / node steps / session trace; `/admin` redirects here |

**UI system:** shadcn under `components/ui/` + semantic tokens in `index.css`; harness-desk values from [`docs/design/`](./design/) **applied**; layers in [`AGENTS.md`](../AGENTS.md). Auth composes `ui/*` + `FormField` / `PasswordBox`; app chrome in `components/` (`AppShell`, `AuthLayout`, `IconButton`, `UserMenu`). Session shell uses content-width `split`/`paged` (`session-layout.ts`); split chat|preview is resizable. Lint/format: Biome (`web/biome.json`; `pnpm run lint`).

**UX features:**

- **Header:** Logo + brand name (top-left); user menu (top-right) with language, theme switch, logout — dropdown on desktop, dialog on mobile
- **i18n:** `react-i18next`, locales `zh-HK` / `en` (default `zh-HK`); UI `zh-HK` follows the Traditional Chinese (Hong Kong) voice in [VOICE.md](./VOICE.md) — extensible via `SUPPORTED_LOCALES`
- **Theme:** Light / dark manual switch (no system mode), persisted in `localStorage`
- **Form memory:** Last user email / display name / org name from `localStorage` (not fake placeholders)
- **Auth:** Access token in memory; refresh via cookie; auto-refresh on app load
- **Phase 3 (shipped):** Chat workspace at `/` — `useSession` REST-first + SSE; Streamdown + `@streamdown/cjk`; live `message.delta`; Agent Mode UI (`agent.progress` trail persisted on user-message `metadata.agent_actions`; brief / `draft.awaiting_image_ok` interrupt; snapshot `interrupted` rehydrates Generate-image CTA); landing recommended-question cards; IG Preview + Confirm; Gemini-style history; **content-based shell** (`split` vs `paged` from pane min-widths, not viewport `lg`; split chat|preview leftover-relative + resizable); paged Chat primary with history icon + Preview via ready banner / **上一頁**; `llm.failed` inline error + Retry; shell fits `h-dvh` with per-pane scroll; no `useChat`
- **Session client:** `web/src/features/session/` — `api.ts` (REST), `sse.ts` (`@microsoft/fetch-event-source` with Bearer), `use-session.ts` + `session-helpers.ts` + `session-layout.ts`, `session-storage.ts` (per-company last session id), `use-recommended-questions.ts`, `components/chat-panel.tsx` + `session-shell.tsx` + `session-history.tsx` + `preview-panel.tsx` + `ig-preview-mock.tsx` + `recommended-questions.tsx`
- **Chat persistence:** Backend writes `session_messages` (user always; assistant for `chat` / `ack_confirm` / LLM failure / review exhausted). Agent turns often **do not** append assistant chat rows — brief/draft live in `sessions.state` + `preview_drafts`. **Agent action trail:** after each turn, `agent.progress` payloads are stored on that turn’s **user** message as `metadata.agent_actions` (`[{node, model_tier, model}, …]`) plus turn wall-clock `metadata.duration_ms`; `GET …/messages` returns `metadata` so refresh rebuilds the trail. In-flight header is `幫緊你幫緊你` / `Working` (static; chevron clickable). After the turn, header is `做咗x秒` / `Worked for`. Chat bubbles themselves have no worked-for row. **Interrupt hydrate:** `sessions.state.awaiting_image_ok` restores the Generate-image card after reopen / switch / API drop. SSE `session.snapshot.interrupted` is parked at `executor_image_plan`, not any in-flight graph `next`. **Hydrate:** `GET /sessions/{id}/messages` + remembered session id in `localStorage`. **History:** split mode left sidebar lists `GET /sessions?company_id=` (pinned group + date groups + search); paged mode opens the same list as a full-page Record view; `PATCH` rename/pin, `DELETE` removes session (+ cascades).

**Run:**

```bash
cd web && pnpm install && pnpm run dev
```

App: http://localhost:5173/login (Vite proxies `/api` → `:8000`; SPA owns `/`, `/login`, `/system`, …)

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
├── scripts/              # export_contracts → docs/openapi.json + docs/contracts/; typescript_gen → FE TS mirrors
├── migrations/           # Alembic (auth → signals → sessions)
├── tests/                # pytest: unit (no DB) + api (TEST_DATABASE_URL)
├── web/                  # React frontend (Phase 3 chat / agent / preview / history UI)
├── AGENTS.md             # Portable coding-agent SSOT (not editor-specific rules)
└── docs/
    ├── ROADMAP.md
    ├── GETTING_STARTED.md
    ├── TESTING.md            # path-tiered coverage gates
    ├── STATUS.md             # this file
    ├── adr/                  # Architecture Decision Records
    ├── contracts/            # JSON Schema mirrors (generated)
    └── openapi.json          # FastAPI OpenAPI (generated)
```

**Tests:** `tests/unit` (no DB) · `tests/api` (requires `TEST_DATABASE_URL`) · `cd web && pnpm test` (Vitest Tier 1/2) · `python -m scripts.eval_agent` (on-demand live LLM). Policy: [TESTING.md](./TESTING.md).

---

## Environment

| Variable | Purpose |
|----------|---------|
| `TEST_DATABASE_URL` | Isolated Postgres for `pytest tests/api` (skipped if unset) |
| `DATABASE_URL` | Async PG URL → dev DB `192.168.5.20:5434/unhinted` |
| `APP_ENV` | `development` (default) or `production` — production refuses weak JWT and a missing/invalid `BYOK_ENCRYPTION_KEY` |
| `ALLOW_INSECURE_JWT` | Escape hatch for local/tests only (`true` skips JWT secret check) |
| `JWT_SECRET` | Sign access/refresh tokens — **≥32 chars + unique** (prod rejects the published `.env.example` default) |
| `BYOK_ENCRYPTION_KEY` | Fernet KEK for org provider keys **and** Instagram tokens at rest ([ADR 0020](./adr/0020-org-byok-keys-models-routing.md), [ADR 0022](./adr/0022-real-publish-instagram.md)). Required in production; generate with `Fernet.generate_key()` |
| `AUTH_RATE_LIMIT_ENABLED` | Rate-limit `/api/auth/register|login|refresh` (default true) |
| `AUTH_RATE_LIMIT_MAX` | Max requests per client IP per window (default 30) |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Sliding window length (default 60) |
| `CORS_ORIGINS` | Default `http://localhost:5173` |
| `OPENAI_API_KEY` | LLM for questions + session nodes + `python -m scripts.eval_agent` |
| `LLM_API_BASE` | Optional OpenAI-compatible proxy base URL (OpenRouter, DeepSeek, Azure, …). When set, model ids go through the OpenAI-compatible client (`openai/` prefix); OpenRouter `org/model` slugs are kept intact |
| `ANTHROPIC_API_KEY` | Optional alternate provider |
| `GEMINI_API_KEY` | Optional native Gemini / Imagen, AI Studio ([ADR 0021](./adr/0021-org-byok-native-gemini.md)) |
| `VERTEX_AI_API_KEY` | Optional Vertex Express API key — not OAuth ([ADR 0021](./adr/0021-org-byok-native-gemini.md)) |
| `GOOGLE_API_KEY` | Optional Vertex Express key when `GOOGLE_GENAI_USE_VERTEXAI=true` (SDK pair; never treated as AI Studio). Do not set the flag in-process |
| `GOOGLE_GENAI_USE_VERTEXAI` | Read-only: `true` routes env `GOOGLE_API_KEY` as Express. `GEMINI_API_KEY` alone is not Express |
| `LLM_CHEAP_MODEL` / `LLM_MEDIUM_MODEL` / `LLM_STRONG_MODEL` | Provider model ids (e.g. `gpt-4o-mini`, `deepseek/deepseek-v4-flash-0731`) |
| `LLM_IMAGE_MODEL` | Image-capable id (e.g. `dall-e-3` / OpenRouter image model). Unset with credentials → error on gen; `placeholder` = mock URL |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | S3-compatible media (MinIO: `docker compose up -d minio minio-init`). Empty endpoint → skip upload |
| `S3_PUBLIC_BASE_URL` | Browser base for object URLs (default `{endpoint}/{bucket}`). Instagram publish needs a Meta-reachable HTTPS URL (local MinIO is not) |
| `PUBLISH_ADAPTER` | Confirm adapter: `stub` (default, never hits Meta) or `instagram` ([ADR 0022](./adr/0022-real-publish-instagram.md)) |
| `META_GRAPH_API_VERSION` | Graph API version pin (default `v22.0`) |
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
| **H2** | Interrupt resume ignores user intent (`ainvoke(None)`) | ✅ **Mitigated** — [ADR 0004](./adr/0004-stop-discard-and-image-resume.md) + [ADR 0016](./adr/0016-queue-send-while-turn-in-flight.md): Stop discards; FE queue while in-flight; `POST /resume-image` only; `/messages` 409 while busy/parked; chat/JSON completions stream + `aclose` on cancel (best-effort upstream abort) |
| **H3** | `use-session.ts` correctness concentrated & untested | ✅ **Mitigated** — pure helpers in `session-helpers.ts` (+ Tier 1 cov gate); `use-session.test.ts` covers restore / send / queue-while-in-flight / optimistic `route_intent` / confirm / SSE merge / switch isolation + composer draft save/restore |
| **I1** | Confirm idempotency key global (cross-user receipt leak) | ✅ **Mitigated** — foreign key → 409; same session/user only replays |

### Other gaps

1. **Phase 3 UI:** Core chat → agent action records (DB-backed on user-message metadata) → preview → confirm stub + history (desktop sidebar / mobile Record–Chat–Preview push pages) shipped. Agent path still rarely writes assistant chat bubbles (brief/preview are side-channel UI). Interrupt Generate-image CTA rehydrates from graph/SSE after fail or refresh.
2. **Phase 2 soft / held:** Image gen via `LLM_IMAGE_MODEL` + MinIO (`S3_*`) when configured; formal curl exit-criteria script still later; `query_market_trends` **schema** landed — adapter wiring still held.
3. **Phase 3 later:** Meta Graph API ingest, BYOK settings page; FB/Threads preview skins. LLM call **records** + admin Trace viewer landed ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md), [ADR 0007](./adr/0007-admin-trace-viewer.md)) — ops guide: [PROMPT_TUNING.md](./PROMPT_TUNING.md). Next: retention/purge policy. `/api` prefix shipped ([ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md)).
4. **Knowledge:** Settings through **K6 Approvals** shipped ([docs/knowledge/](./knowledge/), [ADR 0011](./adr/0011-knowledge-commit-without-llm.md)). Chat scratch still not org KB.
5. **Hardening:** ~~Auth rate limits + JWT secret guard~~ + ~~confirm idempotency user/session scope~~; ~~basic API tests~~ + ~~frontend Vitest Tier 1/2~~ + ~~CI~~ ([TESTING.md](./TESTING.md), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)); ~~contracts SSOT~~ ([AGENTS.md](../AGENTS.md), [adr/](./adr/), [contracts/](./contracts/)); ~~mock-LLM graph node tests + CI Tier 1b~~; ~~interrupt Stop / resume-image ([ADR 0004](./adr/0004-stop-discard-and-image-resume.md))~~; ~~persist LLM call records ([ADR 0005](./adr/0005-platform-levels-and-llm-records.md))~~; ~~`/api` path prefix ([ADR 0006](./adr/0006-api-path-prefix-and-spa-proxy.md))~~; ~~on-demand live eval CLI (`python -m scripts.eval_agent`)~~; multi-worker SSE + turn-stop registry (Redis) if scaling beyond one API process; media private/signed URLs; re-check org membership on session access after revoke; enable branch protection requiring CI checks.

---

## Definition of Done (MVP) — checklist

From ROADMAP; current completion:

1. HK hot search ingests automatically — ✅ (worker + scheduler)  
2. Landing shows ≥5 recommended questions (~12h cache) — ✅ API; ✅ UI (Phase 3 empty-state cards)  
3. User can register, login, access protected dashboard — ✅  
4. Chat → can/cannot recommendation → preview — ✅ API; ✅ chat/brief/preview UI  
5. Unlimited preview revisions + reviewer gate — ✅ API (AI revise); ✅ UI + manual `POST /draft`  
6. Confirm posts via platform API + receipt — 🟡 backend Instagram adapter + org `social_accounts` shipped (default stub); receipt / settings UI still stub ([ADR 0022](./adr/0022-real-publish-instagram.md))  
7. Claims traceable to `source_signal_ids` — ✅ session grounding in graph; ⬜ UI trace links  

---

## References

- [ROADMAP.md](./ROADMAP.md) — full architecture & phase plan
- [GETTING_STARTED.md](./GETTING_STARTED.md) — local setup & run commands
- [TESTING.md](./TESTING.md) — test tiers & path coverage gates
- [README.md](../README.md) — project intro
