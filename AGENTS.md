# Agent brief — Unhinted

Short map for coding agents. Prefer these sources over inventing parallel docs or shapes.

Execution conventions live in `.agents/skills/` — `git-conventions` (branch/commit/PR/review), `alembic-migrations`, `web-ui-system`, `repo-commands`. Load the matching `SKILL.md` before the work; do not keep a second copy in harness-specific packs (`.cursor/rules`, `CLAUDE.md`, and similar).

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
| DB schema history | [`migrations/`](migrations/) | Alembic hex revisions — conventions: `alembic-migrations` skill |
| Test policy | [`docs/TESTING.md`](docs/TESTING.md) | Path-tiered gates; LLM nodes mocked in CI |
| Frontend UI system | [`web/src/components/ui/`](web/src/components/ui/) · [`web/src/index.css`](web/src/index.css) | shadcn primitives + semantic tokens; layers: `web-ui-system` skill |
| Visual design (docs + tokens + Penpot) | [`docs/design/`](docs/design/) · [`design/penpot/`](design/penpot/) | Brief + token inventory + Core `.penpot`; proposed harness desk — CSS apply later |
| Agent execution | this file + `.agents/skills/` | Portable `AGENTS.md` + on-demand skills; not a second product SSOT |

**Runtime state:** REST (e.g. `POST /api/sessions/{id}/messages`) is the client source of truth. SSE is an enhancement layer (live deltas / progress) that merges with dedupe — see [ADR 0002](docs/adr/0002-rest-source-of-truth-sse-enhancement.md). Public HTTP routes live under `/api` ([ADR 0006](docs/adr/0006-api-path-prefix-and-spa-proxy.md)); SPA document routes (`/admin`, …) are separate.

Nested [`web/AGENTS.md`](web/AGENTS.md) and [`migrations/AGENTS.md`](migrations/AGENTS.md) apply when the agent walks `AGENTS.md` from the git root to the current directory. They point at the skills; do not duplicate the rules.

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
5. A feature that adds or changes a contract, routing/behavior rule, or architectural decision gets `docs/adr/NNNN-<slug>.md` (next number) before or with the code — supersede the old ADR rather than rewriting it. Pure bug fixes, docs-only, and chore/tooling changes do not need one.

## Graph node tests (mock LLM)

- CI gates **mock** `complete_json` / repos — **no** `OPENAI_API_KEY` required on GitHub.
- Opt-in step I/O buffer: `node_trace_recording()` in `internal/session/trace.py` (not persisted yet).
- Live LLM evals stay optional / on-demand (`python -m scripts.eval_agent`) — never a required PR check. Cases grade **set coverage** (`queries_require_any`); a red live case means fix the node, not a Latin-only / no-kana prompt patch.
