# ADR 0005 — Platform privilege levels + LLM call records

- **Status:** Accepted
- **Date:** 2026-08-03
- **Supersedes:** — (closes STATUS gap “persist node traces … later”; Trace viewer UI stays deferred)

## Context

Graph nodes and prompts need fine-tuning, but there is no way to see *which step went wrong*: production never enables `node_trace_recording()`, and nothing persists prompts, raw responses, tokens, or latency. At the same time the product needs an **admin area** where privileged users can inspect these records — and there is no platform-level privilege concept at all (`users` has no role column; `organization_members.role` is tenant-scoped and never enforced).

## Decision

### 1. Platform privilege = numeric level on `users`, with named rungs and gaps

New column `users.platform_level` (int, default `3`). Tenant RBAC (`organization_members.role`) stays a separate, per-company concern — platform admin is not an org role (an IT admin belongs to no company).

Named ladder 0–10 with gaps so future rungs slot in without renumbering:

| Level | Name | Use |
|-------|------|-----|
| 0 | `GUEST` | Reserved — unverified / restricted |
| 1 | `TRIAL` | Reserved — trial accounts |
| 3 | `MEMBER` | Default registered user |
| 4 | `MEMBER_PLUS` | Reserved — paid / advanced features |
| 5 | `SUPPORT` | Reserved — internal CS assist; no LLM internals |
| 6 | `ADMIN` | Read-only LLM call records / traces (future IT admin) |
| 7 | `OPS_ADMIN` | Reserved — content ops (signals / questions) |
| 8 | `SECURITY_ADMIN` | Reserved — user / audit management |
| 9 | `SUPERADMIN` | Full — incl. granting/revoking admin (owner only, for now) |
| 10 | `OWNER` | Reserved — system / root |

Checks are threshold-based (`user.platform_level >= required`), implemented as `require_platform_level(...)` in `internal/auth/roles.py`. Only `MEMBER` / `ADMIN` / `SUPERADMIN` are enforced today; the rest are reserved names.

### 2. Bootstrap via CLI, not env or seeds

`python -m cmd.worker set-platform-role --email you@x.com --level superadmin` (name or int). No auto-promote on login, no seed users — admin grants are deliberate, auditable operations.

### 3. Every LLM call is recorded in `llm_call_records`

One row per provider call — session graph nodes (10 LLM nodes) **and** workers (`question_generator`). Instrumented at the single choke point `internal/llm/router.py` (`complete_json` / `complete_text` / `astream_text` / `generate_image`), so nodes/prompts change without touching recording.

Stored per call: correlation (`session_id` / `user_id` / `company_id`, all nullable + `SET NULL`, `caller` e.g. `node:reviewer` / `worker:question_generator`, `node`), request (`kind` chat_json/chat_text/image, `tier`, resolved `model`, `temperature`, full `system_prompt` / `user_prompt`), response (`response_text`, `latency_ms`, token usage), and diagnosis (`status` ok/provider_error/cancelled/empty_response, `error` JSONB, `parse_ok`, `fallback_used`).

### 4. Correlation travels via contextvars; callers mark parse/fallback

- Graph: `graph.py` wraps each LLM node with `recorder.call_context(...)` (ids from state). Workers set their own context.
- Records buffer in the active context and flush (background task, own DB session) when it exits; without a context they persist immediately. `recorder.drain()` lets CLI/scheduler await pending writes before exit.
- `_parse_llm_json` / question generator mark the last call: `parse_ok=False + fallback_used=True` when validation fails and heuristics take over — this is the “which step went wrong” signal. `LlmProviderError` surfaces (no fallback mark), matching existing UI behavior.
- Recording failures never break a turn (logged, swallowed). Toggle: `LLM_RECORD_ENABLED` (default on).
- Streaming calls set `stream_options={"include_usage": true}` for token counts (dropped for unsupported providers; usage then NULL).
- Image `data:` URIs are stored as a size marker, not megabytes of base64. Prompts/responses capped (50k chars).

### 5. Non-LLM node steps stay as-is (for now)

`node_trace_recording()` remains the opt-in test buffer; the per-turn `agent.progress` trail on user-message metadata already lists which nodes ran. Persisting full node-step I/O is a later decision if LLM records prove insufficient.

### 6. Admin API + admin page come after this slice

This ADR lands backend only: schema, privilege infra, recording. `GET /admin/llm-calls*` (gated by `require_platform_level(ADMIN)`), superadmin user management, and the web admin page are follow-up slices.

> **Update (2026-08-03):** `/admin/llm-calls*` API and the web `/admin` records page have shipped (plus `drain()` on API shutdown). Trace viewer / node-step persistence → [ADR 0007](./0007-admin-trace-viewer.md). Still open: superadmin user management API, retention/purge policy.

## Consequences

- New Alembic revision adds `users.platform_level` + `llm_call_records`; existing users default to `MEMBER` (3). The owner must self-grant `SUPERADMIN` via the CLI after migrating.
- `UserResponse` gains `platform_level` (frontend may gate admin UI on it later).
- Every LLM call now does one extra async INSERT; recording is off the critical path (background task) and disabled via `LLM_RECORD_ENABLED=false`.
- Prompts may contain company profile data; records are platform-internal (admin-only reads later). Retention / purge policy is deliberately deferred (dev scale).
- CI graph-node tests still mock the LLM; recorder unit tests mock persistence — no `OPENAI_API_KEY` needed.
