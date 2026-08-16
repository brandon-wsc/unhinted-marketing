# Contract mirrors (generated)

JSON Schema and event catalog exported from Pydantic (`schemas/contracts.py`, `schemas/tools.py`).

Regenerate after changing those models:

```bash
python -m scripts.export_contracts
cd scripts/typescript_gen && npm install && npm run generate
```

Also refreshes [`../openapi.json`](../openapi.json) from the FastAPI app and
`web/src/features/session/generated/` TypeScript mirrors for the session feature.

**Authority:** Python models in `schemas/` — these files are mirrors for agents, FE, and review. Do not edit JSON by hand.
