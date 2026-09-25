# Agent brief — Unhinted Marketing

Short map for coding agents. Prefer these sources over inventing parallel docs or shapes.

Execution conventions (commits, Alembic, web UI) live **in this file**. Do not keep a second copy in harness-specific packs (`.cursor/rules`, `CLAUDE.md`, and similar). A tool may *point* here; it must not own the rules.

## What this is

AI marketing assistant for Hong Kong: background **signal ingest** + user-guided **session** (chat → recommend → preview → confirm). LLM owns the session loop only; **Confirm / publish is traditional HTTP** (no LLM).

## Single sources of truth

| Concern | Authority | Notes |
|---------|-----------|--------|
| Product / architecture | [`docs/ROADMAP.md`](docs/ROADMAP.md) | Modes, graph scope, safety |
| Shipped vs held + decisions | [`docs/STATUS.md`](docs/STATUS.md) | Progress checklists |
| Locked decisions (ADR) | [`docs/adr/`](docs/adr/) | Prefer ADR over chat memory |
| Admin prompt tuning (ops) | [`docs/PROMPT_TUNING.md`](docs/PROMPT_TUNING.md) | How to use LLM records / node steps / Session Trace; retention explained |
| HK social craft (draft voice) | [`docs/VOICE.md`](docs/VOICE.md) | Default editor-voice craft + company `roast_level`; prompts in `internal/session/prompts.py` |
| Enterprise knowledge | [`docs/knowledge/README.md`](docs/knowledge/README.md) | MODEL / SESSION / COLLECT — planes, session contract, ingest |
| HTTP + Pydantic API shapes | [`schemas/`](schemas/) · FastAPI OpenAPI | Export: `python -m scripts.export_contracts` |
| Canonical draft + SSE catalog | [`schemas/contracts.py`](schemas/contracts.py) · [`docs/contracts/`](docs/contracts/) | JSON Schema mirrors |
| External tools | [`schemas/tools.py`](schemas/tools.py) | `query_market_trends`, `publish_social_post` |
| DB schema history | [`migrations/`](migrations/) | Alembic hex revisions — conventions below |
| Test policy | [`docs/TESTING.md`](docs/TESTING.md) | Path-tiered gates; LLM nodes mocked in CI |
| Frontend UI system | [`web/src/components/ui/`](web/src/components/ui/) · [`web/src/index.css`](web/src/index.css) | shadcn primitives + semantic tokens; layers below |
| Visual design (docs + tokens + Penpot) | [`docs/design/`](docs/design/) · [`design/penpot/`](design/penpot/) | Brief + token inventory + Core `.penpot`; proposed harness desk — CSS apply later |
| Agent execution | this file | Portable `AGENTS.md` — commits, Alembic, web UI; not a second product SSOT |

**Runtime state:** REST (e.g. `POST /api/sessions/{id}/messages`) is the client source of truth. SSE is an enhancement layer (live deltas / progress) that merges with dedupe — see [ADR 0002](docs/adr/0002-rest-source-of-truth-sse-enhancement.md). Public HTTP routes live under `/api` ([ADR 0006](docs/adr/0006-api-path-prefix-and-spa-proxy.md)); SPA document routes (`/admin`, …) are separate.

Nested [`web/AGENTS.md`](web/AGENTS.md) and [`migrations/AGENTS.md`](migrations/AGENTS.md) apply when the agent walks `AGENTS.md` from the git root to the current directory. They point back here; do not duplicate the sections.

## Hard boundaries (do not violate)

1. **Confirm ≠ chat** — Publishing only via UI Confirm → `POST /confirm` with `approval_token`. Chat phrases like「可以出」must not publish ([ADR 0003](docs/adr/0003-confirm-without-llm.md)).
2. **Canonical draft** — Shared `{ caption, hashtags, cta }` + media via `preview_images` / `media_ids` ([ADR 0008](docs/adr/0008-preview-images-append-only.md)); `image_url` compat on preview payload ([ADR 0001](docs/adr/0001-preview-canonical-draft.md)).
3. **Knowledge** — PostgreSQL only (signals, entities, edges). No parallel knowledge store.
4. **Org catalog ≠ chat** — Mine propose / Approvals approve-reject are HTTP. Graph nodes must not upsert org products ([ADR 0011](docs/adr/0011-knowledge-commit-without-llm.md)).
5. **Graph scope** — LangGraph = session LLM zone. Preview persist / confirm are outside LLM publish.
6. **Stop ≠ blind resume** — Parked image OK resumes only via `POST /resume-image` ([ADR 0004](docs/adr/0004-stop-discard-and-image-resume.md)). Parked angle pick resumes via `POST /choose-angle` or a typed `POST /messages` ([ADR 0028](docs/adr/0028-angle-pick-before-draft.md)); Stop discards a parked turn, but Stop mid-resume / mid choose-angle re-parks. In-flight Send queues locally (max 3) and holds while the angle park is up ([ADR 0016](docs/adr/0016-queue-send-while-turn-in-flight.md)); in-flight empty Enter with a non-empty queue interrupts (`POST /stop` `mode: "interrupt"` — turn kept) then drains ([ADR 0035](docs/adr/0035-queue-then-interrupt.md)). Image-park explicit Send revises and re-parks — a direction change writes a new script + plan; a caption-only edit keeps the locked plan. It must not Stop and must not blind-resume ([ADR 0036](docs/adr/0036-image-direction-new-script.md), supersedes [ADR 0031](docs/adr/0031-queue-send-while-image-parked.md)). Chat/JSON LLM calls stream + `aclose` on cancel (best-effort upstream abort).

## Before changing behavior

1. Check whether an ADR or STATUS Decision already locks the behavior.
2. If changing a product contract, **update ADR/STATUS first** (or add a superseding ADR), then code + tests.
3. Prefer extending `schemas/` over ad-hoc `dict` payloads for new API or SSE fields.
4. Do not add a second streaming-markdown stack; UI uses Streamdown + `@streamdown/cjk`.

## Graph node tests (mock LLM)

- CI gates **mock** `complete_json` / repos — **no** `OPENAI_API_KEY` required on GitHub.
- Opt-in step I/O buffer: `node_trace_recording()` in `internal/session/trace.py` (not persisted yet).
- Live LLM evals stay optional / on-demand (`python -m scripts.eval_agent`) — never a required PR check. Cases grade **set coverage** (`queries_require_any`); a red live case means fix the node, not a Latin-only / no-kana prompt patch.

## Quick commands

```bash
pip install -e ".[dev]"
pytest tests/unit
pytest tests/unit/test_session_nodes.py tests/unit/test_session_routing.py \
 tests/unit/test_session_angle_gate.py tests/unit/test_session_trace.py \
 tests/unit/test_session_harness.py \
 tests/unit/test_session_research_harness.py \
 tests/unit/test_session_execute_harness.py \
 --cov=internal.session.nodes --cov=internal.session.trace \
 --cov=internal.session.harness --cov=internal.session.research_harness \
 --cov=internal.session.execute_harness --cov=internal.session.ingest --cov-fail-under=70
python -m scripts.export_contracts   # OpenAPI + JSON Schema under docs/
python -m scripts.eval_agent         # on-demand live LLM eval (needs keys; deterministic-only runs go keyless; not CI)
python -m scripts.eval_agent --suite regression   # bigger pack; --out reports/eval/baseline.json refreshes anchor
python -m scripts.eval_diff          # baseline vs latest — exits 1; model change downgrades metrics to warnings (--strict-models fails hard)
python -m scripts.eval_cost_from_records  # prod llm_call_records p50/p95 + ttft + cache hit rate + rough $
cd scripts/typescript_gen && npm install && npm run generate  # session TS mirrors
cd web && pnpm run lint && pnpm test && pnpm run build
cd relay && npm ci && npm run types && npm test   # Cloudflare OAuth relay worker
```

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
type(scope): summary

optional body explaining why
```

- `type` — required; see table below
- `scope` — required; short area (`auth`, `signals`, `web`, `db`, `docs`, `ci`, …)
- `summary` — imperative, lowercase after the colon, ≤72 chars total subject line, no trailing period
- `body` — optional; explain **why**, not a file list. Use bullets for multi-part milestones

```text
✅ feat(signals): bootstrap Phase 1 autopilot for HK signal ingestion
✅ refactor(db): replace hand-rolled Alembic IDs with standard hex revisions
✅ chore(web): upgrade TypeScript 7 and document pgvector setup

❌ Bootstrap Phase 1 autopilot backend…     # missing type(scope)
❌ feat: add stuff                          # missing scope; vague summary
❌ feat(signals): Added signal ingestion.   # past tense + trailing period
```

| Type | When |
|------|------|
| `feat` | New user-facing capability or API |
| `fix` | Bug fix |
| `refactor` | Behavior-preserving code change |
| `docs` | Docs / roadmap / status only |
| `chore` | Tooling, deps, ignore files, misc |
| `test` | Tests only |
| `ci` | CI/CD config |
| `perf` | Performance improvement |

Prefer domain names over roadmap phases for `scope`: `auth`, `signals`, `sessions`, `web`, `db`, `llm`, `workers`, `docs`, `repo`. Prefer why over what. Keep Phase 0/1-style milestone bullets when the commit spans many areas. Never put secrets or env values in messages.

## Alembic migrations

Use Alembic defaults. Do **not** invent sequential IDs (`001_auth`, `002_phase1`).

```
migrations/versions/{rev}_{slug}.py
revision = "{rev}"
```

- `rev` — Alembic-generated hex ID (leave as generated)
- `slug` — short `snake_case` intent from `-m` (domain/capability, not ROADMAP phase)
- Filename stem starts with `revision`; do not rewrite `revision` to match a pretty name

```text
✅ 8791b607d5bc_auth.py       revision = "8791b607d5bc"
✅ 5dae474953cd_signals.py    revision = "5dae474953cd"

❌ 001_auth.py / revision "001_auth"     # hand-rolled sequential ID
❌ 002_phase1_data.py                    # phase name + stem ≠ revision
```

```bash
alembic revision -m "sessions"
# → versions/<hex>_sessions.py with revision = "<hex>"
# keep the generated revision; only edit upgrade/downgrade
```

Name the schema capability (`auth`, `signals`, `sessions`, `campaigns`), not roadmap phases (`phase1`, `phase2`). Do not list every table in the slug; docstring may list tables. Changing `revision` strings requires updating every DB `alembic_version` row (or `alembic stamp`). Prefer not rewriting history once shared.

## Web UI system

| Layer | Role |
|-------|------|
| `web/src/components/ui/*` | shadcn primitives only; own/edit here; add variants via `cva`, don't break call sites |
| `web/src/components/*` | App chrome / composed widgets (`AppShell`, `AuthLayout`, `PasswordBox`) |
| `web/src/features/*/components/*` | Domain UI — compose `ui/*`, no parallel Button/Input/Dialog |
| `web/src/pages/*` | Route shells; keep thin |

- Prefer semantic utilities: `bg-card`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-destructive`, `text-success`, `text-info`, `hover:bg-accent`
- Do **not** invent parallel controls with `var(--color-*)` in classNames; use theme utilities from `index.css` `@theme`
- Raw palette (`bg-blue-600`, `text-zinc-500`) only when no semantic token fits (rare status tones → prefer `Badge` variants)
- **Washes:** `accent` = voice interactive wash (hover / selected / queued). `secondary` = 6% ink|white **resting** wash (tabs track, read-only, notes). Do **not** use `bg-muted` / `hover:bg-muted/*` for hover or selected rows — `--color-muted` is solid `#71717a`, not a soft fill. See [docs/design/TOKENS.md](docs/design/TOKENS.md).
- **Tables:** `TableRow` hover/selected = `bg-accent` (`components/ui/table.tsx`)
- **Fields:** rest `border-input`; hover `border-voice-border`; focus `ring` (voice). View-only uses native `readOnly` (`bg-secondary` wash on `Input` / `Textarea`). Do not `disabled` a field the user should still copy from. `readOnly` must not use the edit `focus-visible` ring (`read-only:focus-visible:ring-0`).

Adding UI: check `components/ui` first; if missing, `pnpm dlx shadcn@latest add <name>`. Never re-export a second `Button` / `Input` / `Dialog` from feature or auth helpers. Prefer composed helpers in `components/` for repeated stacks: `FormField`, `IconButton`.

- `SelectContent` defaults to **`position="popper"`** (dropdown **below** the trigger). Do not revert to Radix `item-aligned`. Popper chrome: `border-border` (+ `dark:border-white/10`), same as `DropdownMenuContent`. Bare `border` inherits ink and reads too dark.
- Prefer standard `sm` / `md` / `lg` for micro chrome only (no one-off `min-[…px]:`)
- Session workspace: **content-based** `split` | `paged` in the shell (`session-layout.ts` + `useContainerWidth`) — do not gate panes on viewport `lg` or device names
- Leaf widgets take a `paged` / mode prop from the shell; they do not decide layout mode themselves

## When reviewing changes

- Flag chat/LLM paths that publish, confirm, or upsert org catalog products; those are HTTP-only (ADR 0003, ADR 0011).
- Flag a second knowledge store or a second streaming-markdown stack.
- Flag hand-rolled Alembic revision IDs and parallel `Button`/`Input`/`Dialog` outside `web/src/components/ui`.
- Leave formatting and lint to CI.
