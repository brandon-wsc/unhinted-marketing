---
name: repo-commands
description: Repo command index for Unhinted — install, unit tests, session-graph coverage runs, contract exports, eval CLIs, TypeScript mirror generation, web and relay builds. Use when you need the exact test, lint, eval, codegen, or build command for this repo.
---

# Repo commands — Unhinted

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
python -m scripts.eval_retrieve      # keyless product-retrieve eval — seeds catalog fixture into scratch pgvector (EVAL_DATABASE_URL, never DATABASE_URL)
python -m scripts.eval_agent --suite regression   # bigger pack; --out reports/eval/baseline.json refreshes anchor
python -m scripts.eval_diff          # baseline vs latest — exits 1; model change downgrades metrics to warnings (--strict-models fails hard)
python -m scripts.eval_cost_from_records  # prod llm_call_records p50/p95 + ttft + cache hit rate + rough $
python -m scripts.check_zone_boundary   # LLM-zone commit boundary — hard boundaries 1/4/5 as a gate
python -m scripts.check_agents_commands # documented commands in AGENTS.md + .agents/skills/ must resolve (CI gate)
python -m scripts.check_contract_drift <base> <head>  # contract-surface diffs need docs/adr|STATUS (CI gate)
cd scripts/typescript_gen && npm install && npm run generate  # session TS mirrors
cd web && pnpm run lint && pnpm test && pnpm run build
cd relay && npm ci && npm run types && npm test   # Cloudflare OAuth relay worker
```
