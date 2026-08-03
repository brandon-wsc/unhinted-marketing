# Testing & Coverage Policy

> **Status:** Backend Tier 1 unit + Tier 2 API landed (`tests/unit`, `tests/api`). Frontend Vitest Tier 1 utils + Tier 2 shared components landed (`cd web && npm test`). GitHub Actions CI in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).  
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
| **1b — Session nodes (mock LLM)** | `internal/session/nodes.py` · `internal/session/trace.py` | **≥70%** | **Fail** — no live LLM; monkeypatch `complete_json` / repos |
| **2 — API** | `cmd/api/routes/**` | **70–80%** | **Fail** — happy path per public endpoint + 401/403 + confirm invalid token / idempotency |
| **3 — Domain** | `internal/auth/service.py` · `deps.py` · `org.py` · non-LLM parts of `internal/session/service.py` | **60–75%** | Soft / follow API tests |
| **4 — Memory glue** | `internal/memory/repos.py` | Covered via API integration | Soft |
| **5 — Omit / smoke** | `internal/session/graph.py` · `prompts.py` · `internal/llm/**` (except focused router unit tests) · `internal/perception/**` · `cmd/worker/**` · `cmd/scheduler/**` · `migrations/**` · `internal/config.py` | **Not in gate** | Live LLM eval = manual / nightly only; `tests/unit/test_llm_router.py` covers provider wrap + stream `aclose` / streamed `complete_json` (no live network) |

**API test priorities (behavior, not %)**:

1. `GET /api/health`
2. Auth: register → login → me → refresh → logout (+ duplicate email, bad password, missing Bearer)
3. Sessions CRUD + ownership `403`
4. Confirm stub: invalid `approval_token` → 400; idempotency replay
5. Signals / questions: auth required

Defer: `POST /messages` graph turns, SSE fan-out, LiteLLM nodes.

### Frontend

| Tier | Paths | Target | Gate |
|------|-------|--------|------|
| **1 — Utils** | `web/src/lib/**` (except deferred `api.ts` fetch wrappers) · `features/session/session-storage.ts` · `features/session/session-helpers.ts` | **85–95%** | **Fail** |
| **2 — Shared (behavioral)** | `components/password-box.tsx` · `components/user-menu-dropdown.tsx` | **50–70%** behavior | Soft floor (50%) in Vitest thresholds |
| **3 — Shared (presentational)** | `app-header.tsx` · `app-logo.tsx` · mostly-layout `auth-layout.tsx` | **Omit** or snapshot optional | No gate |
| **4 — Pages** | `web/src/pages/**` | **20–40%** or smoke only | No hard gate — logic lives in lib/context |
| **5 — Feature UI** | `features/session/components/**` (`chat-panel`, `session-history`, …) | **15–30%** later | No gate in v1 CI |
| **6 — Hooks** | `use-session.ts` (large) · related hooks | **25–40%** progressive | Pure helpers extracted (`session-helpers.ts`); hook suite via mocked RTL `renderHook` — still omitted from hard cov gate |
| **Static** | `npm run build` (`tsc -b && vite build`) | Must pass | **Fail** |

---

## CI gates

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — runs on `push` to `main` and all PRs.

| Job | Checks |
|-----|--------|
| `lint` | `ruff check .` |
| `backend-unit` | `pytest tests/unit` + utils cov ≥85%; session nodes mock-LLM cov ≥70% |
| `backend-api` | `pgvector/pgvector:pg18` service + `pytest tests/api` + routes cov ≥70% |
| `frontend` | `npm ci` → `npm run test:coverage` → `npm run build` |

**Do not** require whole-repo 80%. Local equivalents:

```bash
# Tier 1 utils
pytest tests/unit --cov=internal.auth.jwt --cov=schemas --cov-fail-under=85

# Tier 1b session nodes (mock LLM — no API key)
pytest tests/unit/test_session_nodes.py tests/unit/test_session_routing.py \
  --cov=internal.session.nodes --cov=internal.session.trace --cov-fail-under=70

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
npm test              # vitest run
npm run test:watch    # vitest
npm run test:coverage # vitest run --coverage (path-tiered thresholds)
npm run build
```

If `TEST_DATABASE_URL` is unset, `tests/api` is **skipped**; `tests/unit` still runs.

Coverage omit list for broad reports: see `[tool.coverage.run]` in `pyproject.toml`.

**Frontend notes:** component tests mock `react-i18next` / auth / theme contexts (no full i18n provider). RTL cleanup runs in `web/src/test/setup.ts`. `src/lib/api.ts` fetch wrappers are deferred from the coverage gate.

---

## Investment order

1. ~~**Tier 1 utils** (BE jwt/helpers)~~ — `tests/unit`
2. ~~**Testable app lifespan** (`create_app`) + **Tier 2 API**~~ — `tests/api` + `TEST_DATABASE_URL`
3. ~~**Frontend Vitest**~~ — Tier 1 `web/src/lib/**` + Tier 2 PasswordBox / UserMenuDropdown
4. ~~**CI/CD**~~ — `.github/workflows/ci.yml` (ruff + pytest unit/API + Vitest + build)
5. Hold: SSE E2E, Playwright chat→preview→confirm; live LLM eval = manual/nightly only (`@pytest.mark.live_llm` — not yet wired). **Branch rules:** configured on GitHub but **Not enforced** (account-plan limit) — CI still runs on PRs; merge is not blocked by required checks until enforcement is available.
6. ~~**Contracts SSOT**~~ — `AGENTS.md`, ADRs, `schemas/contracts.py` / `tools.py`, `docs/contracts/` + OpenAPI export
7. ~~**Graph mock-LLM node tests + CI**~~ — `tests/unit/test_session_nodes.py` + routing; opt-in `node_trace_recording()`; CI Tier 1b ≥70%

**Contracts refresh:** after changing `schemas/contracts.py` or `schemas/tools.py` (or API routes), run `python -m scripts.export_contracts` and commit the updated `docs/contracts/` + `docs/openapi.json` mirrors.

**Note:** pytest disables the `debugging` plugin (`-p no:debugging`) because the top-level package name `cmd` shadows the stdlib `cmd` module used by `pdb`.

---

## Related

- Status checklist: [STATUS.md](./STATUS.md) (Automated tests)
- Setup: [GETTING_STARTED.md](./GETTING_STARTED.md)
- Architecture: [ROADMAP.md](./ROADMAP.md)
