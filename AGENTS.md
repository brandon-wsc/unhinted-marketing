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
| HTTP + Pydantic API shapes | [`schemas/`](schemas/) · FastAPI OpenAPI | Export: `python -m scripts.export_contracts` |
| Canonical draft + SSE catalog | [`schemas/contracts.py`](schemas/contracts.py) · [`docs/contracts/`](docs/contracts/) | JSON Schema mirrors |
| External tools | [`schemas/tools.py`](schemas/tools.py) | `query_market_trends`, `publish_social_post` |
| DB schema history | [`migrations/`](migrations/) | Alembic hex revisions — see `.cursor/rules` |
| Test policy | [`docs/TESTING.md`](docs/TESTING.md) | Path-tiered gates; LLM nodes mocked in CI |
| Cursor execution rules | [`.cursor/rules/`](.cursor/rules/) | Scoped (e.g. commits, Alembic); not a second product SSOT |

**Runtime state:** REST (e.g. `POST /sessions/{id}/messages`) is the client source of truth. SSE is an enhancement layer (live deltas / progress) that merges with dedupe — see [ADR 0002](docs/adr/0002-rest-source-of-truth-sse-enhancement.md).

## Hard boundaries (do not violate)

1. **Confirm ≠ chat** — Publishing only via UI Confirm → `POST /confirm` with `approval_token`. Chat phrases like「可以出」must not publish ([ADR 0003](docs/adr/0003-confirm-without-llm.md)).
2. **Canonical draft** — Shared `{ caption, hashtags, cta }` + `image_url`; not per-platform copy trees; not a markdown editor ([ADR 0001](docs/adr/0001-preview-canonical-draft.md)).
3. **Knowledge** — PostgreSQL only (signals, entities, edges). No parallel knowledge store.
4. **Graph scope** — LangGraph = session LLM zone. Preview persist / confirm are outside LLM publish.

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
  --cov=internal.session.nodes --cov=internal.session.trace --cov-fail-under=70
python -m scripts.export_contracts   # OpenAPI + JSON Schema under docs/
cd web && npm test && npm run build
```
