# BYOK Settings — Plan

Status: **design locked via Q&A (2026-08-30), pending ADR**. Decisions below must be
written up as ADR `0020` + STATUS entry before implementation
(see [AGENTS.md](../AGENTS.md) → "Before changing behavior").

Scope: org-level "bring your own key" — provider keys stored encrypted in PostgreSQL,
models registered against those keys, per-tier routing resolved per turn, editable from a
Settings UI. Env keys stay as the platform-level fallback.

---

## 1. Model-layer review (current state)

### What exists

| Piece | File | Notes |
|-------|------|-------|
| LiteLLM router | `internal/llm/router.py` | `complete_json` / `complete_text` / `astream_text` / `generate_image`; tiers `cheap/medium/strong`; `LlmProviderError` taxonomy (timeout/auth/rate_limit/unsupported/…) |
| Pydantic AI harness | `internal/session/harness.py` | `live_harness_model(tier)` builds `OpenAIChatModel` / `AnthropicModel`; shared by chat / research / execute harnesses (ADR 0019) |
| Env config | `internal/config.py` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_API_BASE`, `LLM_*_MODEL`, `LLM_IMAGE_MODEL` |
| Call records | `internal/llm/recorder.py` | `llm_call_records` already carry `company_id` (ADR 0005) — cost attribution per org is free |
| ROADMAP placeholder | `docs/ROADMAP.md` | `byok_config` table named; Phase 3 checkbox "BYOK settings page (masked keys, server-side storage)" |

### Do we support non-OpenAI providers today?

**Partially.** LiteLLM itself is multi-provider, and we expose three env paths:

1. `OPENAI_API_KEY` — native OpenAI.
2. `ANTHROPIC_API_KEY` — Claude (router sets `litellm.anthropic_key`; harness builds `AnthropicModel` when the model id looks like Claude).
3. `LLM_API_BASE` — any OpenAI-compatible endpoint (OpenRouter, DeepSeek, Azure, local gateway); model ids get the `openai/` prefix so LiteLLM uses the compatible client (OpenRouter `org/model` slugs kept).

So DeepSeek / OpenRouter / Claude already work **via env**. Missing: Gemini/other native
provider env vars, per-provider key map, and anything per-org.

### Is the layer abstract enough for BYOK?

**Provider abstraction: yes. Credential scoping: no.** Three concrete gaps:

1. **Credentials are process-global.** `configure_litellm()` mutates `litellm.openai_key` /
   `litellm.anthropic_key` module globals, and `has_llm_credentials()` is a global boolean.
   Two orgs on one deployment cannot use different keys; a request can't carry its own key.
2. **Two resolution paths.** The LiteLLM router and `live_harness_model()` each read
   `settings` directly and each encode provider-detection logic. Per-org resolution must be
   implemented **once** and consumed by both, or they will drift.
3. **Key passing is inconsistent.** `_base_kwargs` only attaches `api_key` when
   `LLM_API_BASE` is set; the plain-OpenAI and Anthropic paths rely on the global mutation.
   BYOK needs explicit per-call `api_key` / `api_base` kwargs everywhere.

None of this blocks the design — the fix is a resolver refactor, not a rewrite.

### API surface (locked premise for provider compatibility)

Everything today runs on **Chat Completions + Images API** — no Responses API anywhere:

- Router: `litellm.acompletion` (`messages` array, streamed deltas) for all chat/JSON calls.
- Harness: `OpenAIChatModel` / `AnthropicModel` — Pydantic AI's Chat Completions path,
  not `OpenAIResponsesModel`.
- Images: `litellm.aimage_generation` (`/v1/images/generations`).

This is BYOK-friendly **by accident, and we now treat it as deliberate**: third-party
OpenAI-compatible providers (DeepSeek, OpenRouter, Azure, local gateways) almost
universally implement Chat Completions only, so the current surface needs zero changes to
route org keys to them.

Two hidden OpenAI-specific assumptions ride on this surface:

- `response_format: {"type": "json_object"}` — legacy JSON mode, not strict `json_schema`.
- `stream_options: {"include_usage": True}` — OpenAI-proprietary usage chunk.

Both are silently dropped for providers that reject them because `litellm.drop_params =
True` is set in `configure_litellm()`. **That flag is the compatibility backstop — do not
remove it** in any refactor; without it, org keys pointing at stricter providers fail on
every call.

Future Responses API adoption (built-in web search, stateful threads, reasoning items)
would need an `OpenAIResponsesModel` branch in the harness plus a degrade strategy for
non-OpenAI org keys — that is a separate ADR, out of scope here.

---

## 2. Locked design decisions (2026-08-30 Q&A)

1. **Decoupled three layers** — keys / model registry / routing are separate. A model is
   registered once (against a key); tiers are pure pointers. Example that drove this:
   register `fable-5`, `deepseek-v4-flash`, `seedream` once each, then
   `strong=fable-5`, `cheap=medium=deepseek-v4-flash`, `image=seedream` — one model
   serving multiple tiers must not require re-entering credentials.
2. **Per-org model overrides in v1** — routing slots are part of the first ship, not
   keys-only. BYOK users on OpenRouter/DeepSeek need custom model ids from day one.
3. **Editor-only visibility** — owner/admin (`COMPANY_SETTINGS_EDITOR_ROLES`) see and
   manage everything; members see nothing (no `is_configured` boolean in v1).
4. **Env keys stay as platform fallback** — orgs without config keep today's behavior;
   dev/eval/CLI unchanged. An org row wins **per slot**: e.g. override `strong` only and
   `cheap/medium/image` keep using the platform key. Platform cost control is a future
   per-org quota concern, not a fallback-granularity concern.
5. **Fixed four routing slots as FK columns** — `cheap / medium / strong / image`,
   matching `ModelTier` + image model. A new tier is a code change anyway
   (`NODE_MODEL_TIERS`, prompts, cost profiles), so JSONB flexibility buys nothing; FK
   integrity does.
6. **Delete = block-then-confirm (two-phase)** — `DELETE` without `force` returns 409 +
   dependent list; UI pops a confirm dialog; `DELETE ?force=true` cascades. Applies to
   both keys (cascade deletes registered models + nulls routing slots) and models (nulls
   routing slots). The 409 response and the force response both report what was/will be
   affected.
7. **Model id source = hybrid fetch** — after entering a key, the UI tries to fetch the
   provider's model list (OpenRouter `/models` returns modality metadata; OpenAI
   `/v1/models` returns ids only). Fetch succeeds → dropdown, and **capability comes from
   provider metadata when available**. Fetch unsupported/fails → free text + inference
   pre-fill (`dall-e` / `seedream` / `flux` / `imagen` → image, else chat) + manual
   override. Capability is never auto-probed with live calls (image probes cost money).
8. **UI flow = wizard + sections** — "Add model" wizard walks key → model id →
   capability (pre-filled) → slot assignment; three management sections (Keys / Models /
   Routing) exist for day-to-day edits.
9. **SSRF guard on user-supplied base URLs** — `api_base` is user input and the server
   fetches it (model-list proxy, test probes). Block private/internal ranges
   (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, link-local /
   cloud-metadata `169.254.0.0/16`, `::1`, etc.), hard timeout, no redirects to internal
   hosts, never forward ambient headers/cookies. P0 security prerequisite, not polish.
10. **Model-list cache is scoped per provider row** — never a global cache keyed by base
    URL alone; one org's key-gated model list must not leak to another org (LibreChat
    shipped this bug). Cache key = provider row id; short TTL; never persisted.
11. **Auto-probe after save** — saving a key or model queues a background auth/format
    probe; the verified badge updates without the user pressing Test (Dify validates on
    save; we keep save non-blocking and probe async). Manual Test stays for re-checks.
12. **Add-model dedupe attaches, not duplicates** — `POST /models` with an existing
    `(provider_id, model_id)` updates that row (e.g. capability correction) instead of
    409 or a duplicate (Dify's attach semantics).

Deferred (note in ADR): key rotation (rotate = re-save all rows), strict env opt-out,
platform-key per-org quotas, Responses API adoption.

### Prior art (checked 2026-08-30)

- **Cline / Roo Code** — provider dropdown → API key → model dropdown fetched from
  OpenRouter `/api/v1/models`, cached locally with fallback to cache on failure;
  capability derived from `architecture.modality`. Validates decisions 7 (hybrid fetch)
  and the capability-from-metadata path.
- **LibreChat** — `models.fetch` against user-supplied base URLs with user-provided
  keys; their bug history is where decisions 9 (SSRF guard) and 10 (per-principal cache
  scoping) come from. Also: never live-revalidate the model list on every message send —
  format-validate only.
- **Dify** — closest analog (multi-tenant workspace SaaS): provider-level credentials
  shared across models, custom models with own credentials, "Default Models" per job
  category (= our routing slots), owner/admin-only management (= decision 3), validate
  credential before enabling (= decision 11), attach-instead-of-duplicate (= decision
  12), keys survive model removal for quick re-add (= consistent with decision 6).

---

## 3. Schema (P0)

Three tables, one Alembic hex revision (`alembic revision -m "byok"`). ROADMAP's
`byok_config` name is superseded by this split (note in ADR 0020).

### `byok_providers` — credentials

| Column | Notes |
|--------|-------|
| `id` | uuid PK |
| `company_id` | FK → entities, index |
| `label` | user-given, e.g. "OpenRouter main" |
| `provider_type` | `openai` \| `anthropic` \| `openai_compatible` (CHECK) |
| `api_key_encrypted` | Fernet ciphertext; never logged, never serialized |
| `key_last4` | masked display + ops correlation |
| `api_base` | nullable; required when `provider_type=openai_compatible` (CHECK: non-empty) |
| `last_verified_at`, `last_error_kind` | filled by the key test endpoint |
| `created_by` / `updated_by`, timestamps | audit (keys only — models have timestamps, no actor columns) |

### `byok_models` — registry

| Column | Notes |
|--------|-------|
| `id` | uuid PK |
| `company_id` | FK → entities, index |
| `provider_id` | FK → `byok_providers` |
| `model_id` | id as the provider expects it |
| `capability` | `chat` \| `image` (CHECK) |
| `capability_source` | `provider_metadata` \| `inferred` \| `manual` (CHECK; audit of how capability was set) |
| `last_verified_at`, `last_error_kind` | filled by the model test endpoint |
| timestamps | no `created_by` / `updated_by` — actor audit lives on the provider key |
| | `unique(provider_id, model_id)` |

### `byok_routing` — per-company slot assignment

| Column | Notes |
|--------|-------|
| `company_id` | PK, FK → entities |
| `cheap_model_id` / `medium_model_id` / `strong_model_id` | nullable FK → `byok_models`; must reference `capability=chat` rows (**app-level**: `PUT /routing` + resolver skip-to-env; not a DB FK — PG cannot bind a constant in an FK without extra columns/triggers) |
| `image_model_id` | nullable FK → `byok_models`; must reference `capability=image` row (same app-level rule) |
| `updated_at` | no `created_at` — one row per company; insert time is not operationally useful |

NULL slot (or no row) → env default for that tier (per-slot fallback, decision 4).

---

## 4. Prerequisites (backend, before any UI)

### P0-1. Encryption at rest

- New env `BYOK_ENCRYPTION_KEY` (Fernet key; `cryptography` is already transitive via
  `python-jose[cryptography]` — promote it to a direct dependency).
- Small helper module (e.g. `internal/llm/keys.py`): `encrypt_key(raw) -> str`,
  `decrypt_key(stored) -> str`, `mask_key(raw) -> last4`. Refuse to start in
  `app_env=production` without the key (same posture as `JWT_SECRET`).

### P0-1b. SSRF guard for user-supplied base URLs (decision 9)

- Shared HTTP helper for all server-side calls to user-supplied `api_base` (model-list
  proxy, test probes): resolve host, reject private/internal/link-local ranges, pin the
  validated address through the request (DNS-rebinding safe), hard timeout, no redirect
  following to re-validated targets only, no ambient headers.
- Actual LLM traffic through LiteLLM/pydantic-ai goes to the same user-supplied base —
  document that the guard covers our probes; LiteLLM calls inherit the org's explicit
  config by design.

### P0-2. Credential resolver (the core refactor)

- New value object `ResolvedModel(model_id, api_key, api_base, provider_type, source:
  "org"|"env", key_last4)`.
- `resolve_llm_model(company_id, tier) -> ResolvedModel` and
  `resolve_image_model(company_id) -> ResolvedModel` — routing slot → registry row →
  provider row (decrypt); NULL slot / no row / `None` company → env default.
- Scope `company_id` per turn via `contextvars` (same pattern as the recorder's
  `call_context`): session service sets it at turn start from `session.company_id`;
  nodes stay untouched.
- Router: `_base_kwargs` / `generate_image` consume the resolved model — pass `api_key` /
  `api_base` explicitly, **stop mutating `litellm` globals** on the org path.
- Harness: `live_harness_model(tier)` consumes the same resolved model (keeps the
  OpenAI/Anthropic construction, gains per-org key + base).
- `has_llm_credentials()` → resolution-aware (`resolve_*` returned a usable key); keep
  the zero-arg env check for CLI/eval scripts.
- **Env behavior must stay bit-identical when no org rows exist** — this refactor lands
  with tests before the API/UI.

### P0-3. Workers

- Question graph runs are **per-company** already → resolve that company's routing; orgs
  without config fall back to env (today's behavior).
- Scheduler fan-out uses each company's own resolution; one org's bad key must not fail
  other orgs' runs (per-run try/except already exists via `question_runs` status).
- `hot_search` needs no LLM — untouched.

### P0-4. Recorder fields

`llm_call_records` gains `key_source` (`env` \| `org`) and `key_last4` (nullable).
Never the raw key, never the ciphertext. Admin `/admin` records viewer can show source
later — not required for v1.

---

## 5. API (P1)

New router `cmd/api/routes/byok.py` under `/api/companies/{id}/byok/…`, all gated by
`require_company_settings_editor` (editor-only reads too — decision 3):

| Endpoint | Behavior |
|----------|----------|
| `GET /providers` | List masked keys: label, provider_type, `key_last4`, api_base, verified status. Never the raw key. |
| `POST /providers` | Add key. Validates shape only — no blocking live call on save; queues a background auth probe (decision 11). |
| `PATCH /providers/{pid}` | Relabel / rotate key / change base URL. Empty `api_key` keeps the stored one. Key/base changes re-queue the probe. |
| `DELETE /providers/{pid}` | Two-phase (decision 6): no `force` → 409 + dependent models; `?force=true` → cascade models + null routing slots, response lists what was removed. |
| `POST /providers/{pid}/test` | Manual auth probe (cheapest possible call); updates `last_verified_at` / `last_error_kind`; returns `{ok, error_kind?}` from the `LlmProviderError.kind` taxonomy. Rate-limited like invites. |
| `GET /providers/{pid}/models` | Proxy the provider's model list (decision 7) through the SSRF guard (decision 9). Returns ids + capability where the provider exposes modality metadata; `{fetchable: false}` when unsupported → UI falls back to free text. Cached briefly **scoped to the provider row** (decision 10); never persisted. |
| `GET /models` | Registry list (joined with masked provider info). |
| `POST /models` | Register model: provider_id + model_id + capability (+ `capability_source`). Existing `(provider_id, model_id)` → update that row, no duplicate (decision 12). Queues a background format probe (decision 11). |
| `DELETE /models/{mid}` | Two-phase: 409 lists referencing slots; `?force=true` nulls those slots, response reports cleared slots. |
| `POST /models/{mid}/test` | Live probe of the model id. Chat probe is a 1-token completion; image probe is opt-in with a cost warning in UI. |
| `GET /routing` | Four slots with resolved effective source (`org` model vs `env` default per slot). |
| `PUT /routing` | Set/clear slots. Validates capability match (chat slots ← `chat` rows, image slot ← `image` row). |

Schemas in a new `schemas/byok.py`; then `python -m scripts.export_contracts` +
`scripts/typescript_gen` mirrors per AGENTS.md.

Security checklist: key never in logs / `llm_call_records` prompts / SSE / OpenAPI
examples; test endpoints rate-limited; decrypt only inside the resolver and test probes.

---

## 6. UI (P2)

New editor-only tab in `web/src/pages/company-settings.tsx` (`?tab=api-keys`, same
gating as `approvals`). New components under
`web/src/features/company-settings/components/` + API functions in the existing `api.ts`.

- **"Add model" wizard** (decision 8): pick existing key or add one inline → model id
  via provider-fetched dropdown, free text when unfetchable → capability pre-filled from
  metadata/inference, overridable → optional slot assignment. Built from `Dialog` +
  `Select` + `Input` primitives.
- **Keys section** — masked rows (`••••{last4}`, label, provider, verified Badge), test
  button, edit (rotate key), delete with the two-phase confirm dialog listing dependents.
- **Models section** — registry rows (model id, key label, capability Badge, verified),
  test button (image test carries a cost warning), delete with slot-impact confirm.
- **Routing section** — four dropdowns (cheap/medium/strong/image), filtered by
  capability; each shows effective source ("Company: fable-5" vs "Platform default");
  clearing a slot reverts to platform.
- i18n: add keys to `zh-HK` + `en` catalogs; spoken-register zh-HK per VOICE decision.
- Compose `ui/*` primitives + `FormField`; no parallel controls (AGENTS.md web rules).

Out of scope for v1 UI: usage/cost display per key (records already carry `company_id` —
admin-side later).

---

## 7. Phasing checklist

- [x] P0-1 encryption helper + `BYOK_ENCRYPTION_KEY` + direct `cryptography` dep
- [x] P0-1b SSRF guard helper for user-supplied base URLs (probes + model-list proxy)
- [x] P0-schema Alembic migration: `byok_providers` / `byok_models` / `byok_routing`
      (hex revision); CHECK on enums + `openai_compatible` requires `api_base`; slot
      capability match is app-level (documented in ADR 0020)
- [x] P0-2 resolver refactor (router + harness + contextvar scoping); env path
      bit-identical; unit tests with mocked resolution (no live key, per TESTING.md)
- [x] P0-3 worker fan-out per-company resolution
- [x] P0-4 recorder `key_source` / `key_last4`
- [x] P1 BYOK routes (providers / models / routing / test / model-list proxy) + schemas +
      contract export + TS mirrors; route tests incl. two-phase delete
- [x] P2 settings tab: wizard + three sections + i18n;
      `pnpm run lint && pnpm test && pnpm run build`
- [x] ADR 0020 + STATUS decision entry; tick ROADMAP "BYOK settings page" (rename to
      match the three-table design); update `.env.example` (`BYOK_ENCRYPTION_KEY`)
