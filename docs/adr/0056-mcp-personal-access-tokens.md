# ADR 0056 — Personal access tokens for headless MCP clients

- **Status:** Accepted
- **Date:** 2026-10-25
- **Supersedes:** —
- **Amends:** [ADR 0051](./0051-remote-mcp-server.md) (§4 grants and tokens, §5 scopes — adds a non-OAuth mint path)
- **Related:** [ADR 0003](./0003-confirm-without-llm.md), [ADR 0041](./0041-member-usage-limits-and-publish-approval.md), [ADR 0046](./0046-account-settings-profile.md), [ADR 0053](./0053-mcp-cimd-loopback-redirect.md)

## Context

[ADR 0051](./0051-remote-mcp-server.md) makes `/api/mcp` an OAuth 2.1 resource server where the only credential is an access token minted through the authorize → consent → code → token chain. That covers interactive clients — Claude, ChatGPT, Grok — where a human drives a browser through consent.

It does not cover clients that run without a person:

- **Header-configured agents.** Hermes Agent and similar local agents configure a remote server as `url` + static `headers` (`Authorization: Bearer …`). They have no OAuth dance to run — they want a token to paste.
- **Our own bots.** The internal Grok bot gateway authenticates to services with a static gateway token, the same pattern.
- **CI and automation.** Any unattended caller.

This is not a compatibility shim that goes away when clients catch up. OAuth needs a human; machine-to-machine identity is a permanent lane — mainstream hosted MCP servers (Linear, GitHub, Notion) all accept a first-party PAT or API key as `Authorization: Bearer` alongside OAuth. The MCP spec leaves non-OAuth credential schemes to the server; nothing in `2026-07-28` forbids a static bearer on the resource endpoint.

Dynamic Client Registration is deliberately still not offered — it fixes a different problem (DCR-only clients like Gemini's connected apps) and stays out.

## Decision

### 1. Token shape

- A personal access token (PAT) is `unh_` + `secrets.token_urlsafe(36)` — an opaque bearer, visibly prefixed for leak scanning and so the auth path can dispatch on it.
- The plaintext is shown **once** at mint. The DB stores `sha256(token)` via the existing `hash_refresh_token` convention, never the token.
- `expires_at` is optional: the mint UI offers a fixed set of lifetimes plus never-expire. An expired PAT is refused like a revoked one.

### 2. A PAT is a self-issued grant

- Minting a PAT creates an `oauth_grants` row exactly like the consent path: same `user_id`, one `company_id`, a scope set, `last_used_at`, `revoked_at`. `client_id` is the per-token URN `urn:unhinted:pat:<token-row-id>`; `client_name` is the user's label (e.g. "Hermes 機器").
- Every live re-check in [ADR 0051](./0051-remote-mcp-server.md) §4 therefore applies unchanged: grant not revoked, user active, membership still exists. Revoking the grant — the same `/account` connected-apps row and `DELETE` — kills the PAT on the next call.
- `sessions.origin` and rate limiting need no change: they already key off the grant (`kind: "mcp"`, `client_id`, `client_name`).

### 3. `mcp_personal_tokens` table

| Column | Purpose |
|---|---|
| `id` | PK; also embedded in `client_id` so the grant URN is unique per token (the `(user_id, client_id, company_id)` uniqueness then never blocks multiple PATs per company) |
| `grant_id` | FK → `oauth_grants`, unique, cascade — the row exists only to resolve token → grant |
| `token_hash` | `sha256(token)`, unique |
| `token_prefix` | First 12 chars (e.g. `unh_aB3d…`) for display in the connected-apps list |
| `expires_at` | nullable — `null` = never expires |
| `created_at` | server default |

- A user may hold at most **20 live PATs**; minting past the cap is refused (400) until one is revoked. PATs share the grant's per-company binding — one company per token, same as consent.
- No refresh and no rotation: a PAT is the credential. Compromise → revoke and mint a new one.

### 4. Bearer dispatch at `/api/mcp`

- `get_mcp_context` dispatches on the `unh_` prefix: PAT → `sha256` lookup → grant → synthetic `McpAccessClaims` (`sub`, `cid`, `gid`, `scope` from the live grant row); anything else → the existing `mcp_access` JWT path.
- A PAT is only ever resolved inside `get_mcp_context`. Every other `/api` route verifies `access`-type JWTs, so a PAT cannot reach them — same isolation guarantee as §4 of ADR 0051, one direction reversed.
- An unknown, expired, or grant-revoked PAT produces the same 401 challenge as a bad JWT; the error does not distinguish "no such token" from "wrong scheme".

### 5. Scopes

- Defaults to the same `DEFAULT_SCOPES` as consent (`knowledge:read`, `drafts:write`). `images:generate` is an explicit opt-in at mint — same step-up posture as the consent page, with the same "spends your token quota" warning.
- The scope universe is unchanged (`MCP_TOOL_SCOPES`): no publish, no Confirm, no catalog writes — those scopes do not exist.

### 6. API and UI

- `POST /api/auth/me/mcp-tokens` — `{name, company_id, expires_in_days?, extra_scopes?}` → `{token, app}` where `app` is the connected-app row. `extra_scopes` is validated against `STEP_UP_SCOPES` exactly like consent extras; the default scope set is not a parameter.
- `GET /api/auth/me/connected-apps` and `DELETE …/{grant_id}` already cover PATs; each row gains `kind: "oauth" | "pat"` and `token_prefix`/`expires_at` so the UI can badge and hint tokens.
- `/account` gains a mint form (label, company, lifetime, images opt-in) and shows the minted token once in a `CopyField`. The connect card gains a "Hermes / CLI agents" tab with the `Authorization: Bearer` config shape; the Gemini tab is demoted to a note — it explains why Gemini cannot connect, it is not a path.

## Consequences

- Header-only clients (Hermes Agent `mcp_servers.<name>.url + headers`, the Grok bot gateway, CI) can reach `/api/mcp` with `Authorization: Bearer unh_…`.
- Revocation, membership checks, scopes, provenance, and connected-apps UI are all reuse — the PAT surface is a lookup table plus one dispatch branch in `get_mcp_context`.
- PATs are bearer secrets with optional no-expiry: the shown-once rule, hash-at-rest, the 20-token cap, and the `unh_` prefix (for secret scanning) are the mitigations. There is no audience claim — a leaked PAT is valid until revoked, so `last_used_at` on the grant doubles as the compromise signal.
- The token endpoint is an authenticated write; it inherits the web session's CSRF/rate posture rather than the unauthenticated OAuth endpoint limits.

## Out of scope

- Org-level service tokens (still per-user grants, as ADR 0051 says).
- Dynamic Client Registration — DCR-only clients (Gemini connected apps) still cannot connect.
- PAT rotation or scoped-down sub-tokens.
- MCP Apps / Tasks changes.
