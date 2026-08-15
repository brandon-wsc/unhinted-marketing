# Agent brief — Unhinted Marketing

Short map for coding agents. Prefer these sources over inventing parallel docs or shapes.

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
| DB schema history | [`migrations/`](migrations/) | Alembic hex revisions — see `.cursor/rules` |
| Test policy | [`docs/TESTING.md`](docs/TESTING.md) | Path-tiered gates; LLM nodes mocked in CI |
| Frontend UI system | [`web/src/components/ui/`](web/src/components/ui/) · [`web/src/index.css`](web/src/index.css) | shadcn primitives + semantic tokens; layers in [`.cursor/rules/web-ui-system.mdc`](.cursor/rules/web-ui-system.mdc) |
| Visual design (docs + tokens + Penpot) | [`docs/design/`](docs/design/) · [`design/penpot/`](design/penpot/) | Brief + token inventory + Core `.penpot`; proposed harness desk — CSS apply later |
| Cursor execution rules | [`.cursor/rules/`](.cursor/rules/) | Scoped (e.g. commits, Alembic, web UI); not a second product SSOT |

**Runtime state:** REST (e.g. `POST /api/sessions/{id}/messages`) is the client source of truth. SSE is an enhancement layer (live deltas / progress) that merges with dedupe — see [ADR 0002](docs/adr/0002-rest-source-of-truth-sse-enhancement.md). Public HTTP routes live under `/api` ([ADR 0006](docs/adr/0006-api-path-prefix-and-spa-proxy.md)); SPA document routes (`/admin`, …) are separate.

## Hard boundaries (do not violate)

1. **Confirm ≠ chat** — Publishing only via UI Confirm → `POST /confirm` with `approval_token`. Chat phrases like「可以出」must not publish ([ADR 0003](docs/adr/0003-confirm-without-llm.md)).
2. **Canonical draft** — Shared `{ caption, hashtags, cta }` + media via `preview_images` / `media_ids` ([ADR 0008](docs/adr/0008-preview-images-append-only.md)); `image_url` compat on preview payload ([ADR 0001](docs/adr/0001-preview-canonical-draft.md)).
3. **Knowledge** — PostgreSQL only (signals, entities, edges). No parallel knowledge store.
4. **Org catalog ≠ chat** — Mine propose / Approvals approve-reject are HTTP. Graph nodes must not upsert org products ([ADR 0011](docs/adr/0011-knowledge-commit-without-llm.md)).
5. **Graph scope** — LangGraph = session LLM zone. Preview persist / confirm are outside LLM publish.
6. **Stop ≠ blind resume** — Parked image OK resumes only via `POST /resume-image`; Stop discards the turn ([ADR 0004](docs/adr/0004-stop-discard-and-image-resume.md)). Chat/JSON LLM calls stream + `aclose` on cancel (best-effort upstream abort).

## Before changing behavior

1. Check whether an ADR or STATUS Decision already locks the behavior.
2. If changing a product contract, **update ADR/STATUS first** (or add a superseding ADR), then code + tests.
3. Prefer extending `schemas/` over ad-hoc `dict` payloads for new API or SSE fields.
4. Do not add a second streaming-markdown stack; UI uses Streamdown + `@streamdown/cjk`.

## Graph node tests (mock LLM)

- CI gates **mock** `complete_json` / repos — **no** `OPENAI_API_KEY` required on GitHub.
- Opt-in step I/O buffer: `node_trace_recording()` in `internal/session/trace.py` (not persisted yet).
- Live LLM evals stay optional / manual — never a required PR check.

## Quick commands

```bash
pip install -e ".[dev]"
pytest tests/unit
pytest tests/unit/test_session_nodes.py tests/unit/test_session_routing.py \
 tests/unit/test_session_trace.py \
 --cov=internal.session.nodes --cov=internal.session.trace --cov-fail-under=70
python -m scripts.export_contracts   # OpenAPI + JSON Schema under docs/
cd web && pnpm run lint && pnpm test && pnpm run build
```
