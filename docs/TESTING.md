# Testing & Coverage Policy

> **Status:** Backend Tier 1 unit + Tier 2 API landed (`tests/unit`, `tests/api`). Frontend Vitest Tier 1 utils + Tier 2 shared components landed (`cd web && pnpm test`). GitHub Actions CI in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).  
> **Principle:** path-tiered gates — **no single repo-wide 80%**. Utils and API earn hard floors; pages / large feature UI / LLM stay low or omitted.

---

## Why tiers differ

| Layer | Why the bar is different |
|-------|--------------------------|
| **Utils** | Pure transforms, no UI/IO; cheap to unit-test; bugs fan out widely |
| **API** | Product contract + auth/ownership boundaries; integration tests, not line-count vanity |
| **Shared components** | Test **behavior** (toggle, menu, a11y), not every className |
| **Pages** | Thin shells over lib/context; line coverage is a poor signal |
| **Feature UI / hooks** | Large, SSE/LLM-coupled; brittle under shallow RTL — prefer smoke / later E2E |
| **LLM / workers** | Expensive mocks, flaky; excluded from merge gates |

---

## Coverage targets by path

Targets are **line coverage** unless noted. CI should enforce **per-path** (or per-job) floors — never one global `--cov-fail-under` for the whole tree.

### Backend

| Tier | Paths | Target | Gate |
|------|-------|--------|------|
| **1 — Utils** | `internal/auth/jwt.py` · `schemas/**` · pure helpers in `internal/session/service.py` (`normalize_draft_copy`, `preview_updated_payload`, …) · `internal/session/checkpointer.py` (`checkpoint_conninfo`) · `internal/session/tiers.py` · `internal/session/io.py` / `state.py` (pure bits) | **85–95%** | **Fail** |
| **1b — Session nodes (mock LLM)** | `internal/session/nodes.py` · `internal/session/trace.py` · `internal/session/harness.py` · `internal/session/research_harness.py` · `internal/session/execute_harness.py` · `internal/session/ingest.py` | **≥70%** | **Fail** — no live LLM; monkeypatch `complete_json` / repos / `TestModel` |
| **2 — API** | `cmd/api/routes/**` | **70–80%** | **Fail** — happy path per public endpoint + 401/403 + confirm invalid token / idempotency |
| **3 — Domain** | `internal/auth/service.py` · `deps.py` · `org.py` · non-LLM parts of `internal/session/service.py` | **60–75%** | Soft / follow API tests |
| **4 — Memory glue** | `internal/memory/repos.py` | Covered via API integration | Soft |
| **5 — Omit / smoke** | `internal/session/graph.py` · `prompts.py` · `internal/llm/**` (except focused unit tests) · `internal/perception/**` · `cmd/worker/**` · `cmd/scheduler/**` · `migrations/**` · `internal/config.py` | **Not in gate** | Live LLM eval = on-demand CLI (`python -m scripts.eval_agent`); never a PR required check. Focused (no live network): `tests/unit/test_llm_router.py` (provider wrap + stream `aclose` / streamed `complete_json`; Vertex Express skips LiteLLM), `tests/unit/test_llm_resolve.py` (env vs org, Gemini vs Express keys), `tests/unit/test_llm_probes.py` (catalog parse/merge, format probe, Express `generateContent` ping). Graders: `tests/unit/test_eval_graders.py` · `tests/unit/test_eval_voice_judge.py` |

**API test priorities (behavior, not %)**:

1. `GET /api/health`
2. Auth: register → login → me → refresh → logout (+ duplicate email, bad password, missing Bearer)
3. Sessions CRUD + ownership `403` + **teammate isolation** (same org, different `user_id` — `tests/api/test_session_isolation.py`)
4. Confirm: invalid `approval_token` → 400; idempotency replay; copy-only → `400 image_required`; Instagram adapter with no account → `400 social_account_not_connected`; failed publish leaves `session.status` unconfirmed (`tests/api/test_confirm.py`). Adapter Graph calls mocked in `tests/unit/test_publish.py` (never live Meta). Tests pin `PUBLISH_ADAPTER=stub` so a local `.env` cannot reach Meta.
5. Signals / questions: auth required
6. Org invites: create → list → revoke → accept; email bind; bootstrap replace (ADR 0013); 409 only for a real team (`tests/api/test_company_invites.py`)
7. Product proposals (K6): Mine propose → list → approve upserts org / reject leaves org empty; 409 pending SKU; cannot propose org or others' Mine; member cannot approve; reject then re-propose; proposer can cancel then re-propose; snapshot frozen after propose; approve replaces existing org SKU (`tests/api/test_product_proposals.py`)
8. Product catalog: PATCH keeps extra import columns; create/patch SKU clash → 409 `sku_taken` + `suggested_sku` (no silent overwrite) (`tests/api/test_company_products.py`)
9. Social accounts (ADR 0022): editor CRUD; member 403; response never leaks the raw token (`tests/api/test_company_social.py`). Instagram Login start/status/cancel/callback (happy path + `meta_oauth_not_professional` / `meta_oauth_missing_publish` redirects); Graph mocked, never live Meta (`tests/api/test_social_oauth.py`). Connect helpers: `tests/unit/test_meta_oauth.py`.
10. Storage config (ADR 0025): editor GET/PUT `/storage/config` + `/test`; migrate copy → flip → rollback → clean; member 403; secret never in the response (`tests/api/test_company_storage.py`).

Defer: `POST /messages` graph turns, SSE fan-out, LiteLLM nodes.

### Frontend

| Tier | Paths | Target | Gate |
|------|-------|--------|------|
| **1 — Utils** | `web/src/lib/**` (except deferred `api.ts` fetch wrappers) · `features/session/session-storage.ts` · `features/session/session-helpers.ts` · `features/session/session-layout.ts` | **85–95%** | **Fail** |
| **2 — Shared (behavioral)** | `components/password-box.tsx` · `components/user-menu-dropdown.tsx` | **50–70%** behavior | Soft floor (50%) in Vitest thresholds |
| **3 — Shared (presentational)** | `app-header.tsx` · `app-logo.tsx` · mostly-layout `auth-layout.tsx` · `form-field.tsx` · `icon-button.tsx` | **Omit** or snapshot optional | No gate |
| **4 — Pages** | `web/src/pages/**` | **20–40%** or smoke only | No hard gate — logic lives in lib/context. Invite accept smoke: `?next=` + action order (return left / accept right) + logged-in email `readOnly` in `invite-accept.test.tsx` |
| **5 — Feature UI** | `features/session/components/**` (`chat-panel`, `session-history`, …) | **15–30%** later | No gate in v1 CI — shell mode logic covered via `session-layout.ts` |
| **6 — Hooks** | `use-session.ts` (large) · `use-container-width.ts` · related hooks | **25–40%** progressive | Pure helpers extracted (`session-helpers.ts` / `session-layout.ts`); hook suite via mocked RTL `renderHook` — still omitted from hard cov gate |
| **Static** | `pnpm run lint` (Biome) · `pnpm run build` (`tsc -b && vite build`) | Must pass | **Fail** |

---

## CI gates

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — runs on `push` to `main` and all PRs.

| Job | Checks |
|-----|--------|
| `lint` | `ruff check .` |
| `backend-unit` | `pytest tests/unit` + utils cov ≥85%; session nodes mock-LLM cov ≥70% |
| `backend-api` | `pgvector/pgvector:pg18` service + `pytest tests/api` + routes cov ≥70% |
| `frontend` | `pnpm install --frozen-lockfile` → `pnpm run lint` (Biome) → `pnpm run test:coverage` → `pnpm run build` |
| `contracts` | `python -m scripts.check_contracts_fresh`; regenerate TS via `scripts/typescript_gen` and `git diff --exit-code` on `web/src/features/session/generated/` |

**Do not** require whole-repo 80%. Local equivalents:

```bash
# Tier 1 utils
pytest tests/unit --cov=internal.auth.jwt --cov=schemas --cov-fail-under=85

# Tier 1b session nodes (mock LLM — no API key)
pytest tests/unit/test_session_nodes.py tests/unit/test_session_routing.py \
 tests/unit/test_session_angle_gate.py tests/unit/test_session_trace.py \
 tests/unit/test_session_harness.py \
 tests/unit/test_session_research_harness.py \
 tests/unit/test_session_execute_harness.py \
 --cov=internal.session.nodes --cov=internal.session.trace \
 --cov=internal.session.harness --cov=internal.session.research_harness \
 --cov=internal.session.execute_harness --cov=internal.session.ingest --cov-fail-under=70

# Tier 2 API routes (needs TEST_DATABASE_URL)
pytest tests/api --cov=cmd.api.routes --cov-fail-under=70
```

Frontend Vitest instrumentation (see `web/vite.config.ts`):

```text
include: src/lib/** , session-storage.ts , session-helpers.ts , password-box.tsx , user-menu-dropdown.tsx
omit:   src/pages/** , src/features/session/components/** , src/main.tsx ,
        use-session.ts , src/lib/api.ts (fetch wrappers deferred)
```

---

## Local commands

```bash
pip install -e ".[dev]"

# Tier 1 unit — no Postgres
pytest tests/unit

# Tier 2 API — requires a dedicated test database (never use prod / shared dev blindly)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@HOST:PORT/unhinted_test
pytest tests/api

# Path-tiered coverage (examples — use dotted module paths)
pytest tests/unit --cov=internal.auth.jwt --cov=schemas --cov-fail-under=85
TEST_DATABASE_URL=... pytest tests/api --cov=cmd.api.routes --cov-fail-under=70

# Frontend
cd web
pnpm run lint          # biome check .
pnpm run lint:fix     # biome check --write .
pnpm test              # vitest run
pnpm run test:watch    # vitest
pnpm run test:coverage # vitest run --coverage (path-tiered thresholds)
pnpm run build
```

On-demand live LLM eval (not CI). Needs `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. Writes `reports/eval/latest.md` + `latest.json` (gitignored). Draft cases get a cheap-model VOICE judge (`scene` / `layers` / `bridge` / `locale` → `overall` 0–1); YAML `expect.min_voice` / `max_voice` can fail a case (PR-tone fixture is `voice_pr_tone_negative`). `--skip-judge` runs code graders only.

Query cases grade the **set**: `queries_require_any` (each group must match at least one query — follow-up must keep prior intent **and** the new sense). Do **not** ban kana/CJK globally. `queries_forbid_cjk` is only for cases that must gloss mixed `entity_surface` (e.g. first-turn `usagi 兔糧` → English). A red live case means fix the node, not the grader or prompt example. Graders: `tests/unit/test_eval_graders.py` · `tests/unit/test_eval_voice_judge.py`.

```bash
python -m scripts.eval_agent              # suite=smoke
python -m scripts.eval_agent --suite research
python -m scripts.eval_agent --suite all
python -m scripts.eval_agent --skip-judge
```

If `TEST_DATABASE_URL` is unset, `tests/api` is **skipped**; `tests/unit` still runs.

Coverage omit list for broad reports: see `[tool.coverage.run]` in `pyproject.toml`.

**Frontend notes:** component tests mock `react-i18next` / auth / theme contexts (no full i18n provider). RTL cleanup runs in `web/src/test/setup.ts`. `src/lib/api.ts` fetch wrappers are deferred from the coverage gate.

---

## Investment order

1. ~~**Tier 1 utils** (BE jwt/helpers)~~ — `tests/unit`
2. ~~**Testable app lifespan** (`create_app`) + **Tier 2 API**~~ — `tests/api` + `TEST_DATABASE_URL`
3. ~~**Frontend Vitest**~~ — Tier 1 `web/src/lib/**` + Tier 2 PasswordBox / UserMenuDropdown
4. ~~**CI/CD**~~ — `.github/workflows/ci.yml` (ruff + pytest unit/API + Biome + Vitest + build)
5. Hold: SSE E2E, Playwright chat→preview→confirm. **Live LLM eval CLI landed** — `python -m scripts.eval_agent` (on-demand; not a PR job). `@pytest.mark.live_llm` remains unused. **Branch rules:** configured on GitHub but **Not enforced** (account-plan limit) — CI still runs on PRs; merge is not blocked by required checks until enforcement is available.
6. ~~**Contracts SSOT**~~ — `AGENTS.md`, ADRs, `schemas/contracts.py` / `tools.py`, `docs/contracts/` + OpenAPI export
7. ~~**Graph mock-LLM node tests + CI**~~ — `tests/unit/test_session_nodes.py` + routing; opt-in `node_trace_recording()`; CI Tier 1b ≥70%

**Contracts refresh:** after changing `schemas/contracts.py` or `schemas/tools.py` (or API routes), run `python -m scripts.export_contracts`, then `cd scripts/typescript_gen && npm install && npm run generate`, and commit the updated `docs/contracts/`, `docs/openapi.json`, and `web/src/features/session/generated/` mirrors.

**Note:** pytest disables the `debugging` plugin (`-p no:debugging`) because the top-level package name `cmd` shadows the stdlib `cmd` module used by `pdb`.

---

## Related

- Status checklist: [STATUS.md](./STATUS.md) (Automated tests)
- Setup: [GETTING_STARTED.md](./GETTING_STARTED.md)
- Architecture: [ROADMAP.md](./ROADMAP.md)
