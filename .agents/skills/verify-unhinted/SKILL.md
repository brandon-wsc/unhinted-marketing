---
name: verify-unhinted
description: Drive a locally launched Unhinted API the way a user does — on-prem first-run setup, auth, and session workspace over real HTTP against a fresh migrated Postgres — and capture evidence. Use when a change can affect /api routes, auth, session CRUD, or the confirm flow, and the proof has to be a real response from a stack this run started.
---

# Verify Unhinted

Prove behavior on a local API + Postgres this run started. Do not attach to an already-running uvicorn on :8000, and do not touch the dev `docker compose` database or its `pgdata18` volume. Two runs get two run dirs; a second API needs `VERIFY_API_PORT` and (container mode) `VERIFY_PG_PORT`.

This checks the local dev stack (uvicorn + pgvector Postgres + Alembic migrations). It does not open `https://unhinted.hk`, the demo host, Meta/Instagram, or live LLM providers — those stay unverified unless the matching key is passed through (see `session-chat` in `features/`).

## Launch

From the repo root:

```bash
.agents/skills/verify-unhinted/scripts/verify.sh launch
```

Postgres comes from one of two modes, picked automatically:

- **shared** — if `postgresql://postgres:postgres@127.0.0.1:5432/postgres` (the dev `docker compose` db's admin DSN, override with `VERIFY_PG_ADMIN_DSN`) accepts a connection, the run creates scratch database `unhinted_verify_<runid>` there. Your dev data is untouched; cleanup drops only the scratch db.
- **container** — otherwise the run starts `pgvector/pgvector:pg18` as `unhinted-verify-pg-<runid>` on `127.0.0.1:55432` (`VERIFY_PG_PORT`).

Then `alembic upgrade head` runs against the fresh DB (migrations create `CREATE EXTENSION vector` themselves) and `uvicorn cmd.api.main:app` starts on `127.0.0.1:8871` with env isolated per run — own `JWT_SECRET`, `MEDIA_ROOT` under the run dir, `PUBLISH_ADAPTER=stub`, `DEPLOYMENT_MODE=onprem`, rate limits off. `OPENAI_API_KEY`, `LLM_*`, `TAVILY_API_KEY`, `BYOK_ENCRYPTION_KEY` pass through only when set in your shell.

Ready means `GET /api/health` returns `{"status":"ok"}` **and** `GET /api/setup/status` answers — the second query hits the DB, so a passing launch proves migrated-DB connectivity, not just a listening port.

## Doctor

```bash
.agents/skills/verify-unhinted/scripts/verify.sh doctor
```

Answers whether this instance is worth driving: recorded api pid alive and owning `$VERIFY_API_PORT`, Postgres reachable (container `State.Running` or shared probe), `/api/health` ok, `/api/setup/status` parses (DB-backed). Writes `evidence/<run-id>/doctor.json` and exits non-zero on any failed check. Run this first whenever anything looks off — and before trusting a stale run dir.

## Drive

Read `features/README.md`, then the feature file. Recipes:

```bash
.agents/skills/verify-unhinted/scripts/verify.sh drive first-run-setup
.agents/skills/verify-unhinted/scripts/verify.sh drive session-workspace
.agents/skills/verify-unhinted/scripts/verify.sh drive all
```

`first-run-setup` claims the fresh instance via `POST /api/setup` (the on-prem wizard's HTTP path) and leaves `state/auth.json` behind — the other drives reuse it. `session-workspace` drives session create/list/rename/messages/delete with that token, LLM-free (`POST /sessions` without `initial_message` never touches the graph). Features that need the session graph or live providers are mapped in `features/` but not scripted — follow the feature file's curl recipe yourself.

Evidence lands in `.agents/skills/verify-unhinted/evidence/<run-id>/` — every step records `{http_status, body}` (or `raw_body`). Tokens inside are scoped to the throwaway run.

## Cleanup

```bash
.agents/skills/verify-unhinted/scripts/verify.sh cleanup
```

Kills the recorded api pid (never by name), stops the `unhinted-verify-pg-*` container or drops the scratch `unhinted_verify_*` database, copies `api.log` into `evidence/<run-id>/`, then removes the run dir. Evidence survives cleanup — the script fails loudly if the evidence dir is gone afterward. Stray containers from crashed runs match `docker ps -a --filter name=unhinted-verify-pg-`.
