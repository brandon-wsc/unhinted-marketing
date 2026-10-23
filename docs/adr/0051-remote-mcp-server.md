# ADR 0051 — Remote MCP server for consumer AI apps

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes:** —
- **Amends:** [ADR 0006](./0006-api-path-prefix-and-spa-proxy.md) (root `/.well-known/oauth-*` exception, §2); [ADR 0029](./0029-angle-persona-bundled-gate.md) / [ADR 0030](./0030-image-format-in-bundled-gate.md) (a gate answer may come from an MCP client; brief gains `recommended_angle_index`, §9–§10)
- **Related:** [ADR 0002](./0002-rest-source-of-truth-sse-enhancement.md), [ADR 0003](./0003-confirm-without-llm.md), [ADR 0004](./0004-stop-discard-and-image-resume.md), [ADR 0011](./0011-knowledge-commit-without-llm.md), [ADR 0019](./0019-pydantic-ai-inner-harness.md), [ADR 0026](./0026-onprem-first-run-setup.md), [ADR 0036](./0036-image-direction-new-script.md), [ADR 0041](./0041-member-usage-limits-and-publish-approval.md), [ADR 0045](./0045-honest-citations-preview-identity-sse-h2.md), [ADR 0046](./0046-account-settings-profile.md)

## Context

Users already hold conversation context in consumer AI apps (Claude, ChatGPT, Gemini). We hold what those apps lack: company voice and `roast_level`, the org product catalog, HK signals, and a connected Instagram account. Users want to turn context from those apps into a post through us, without re-explaining it in our chat and without clicking through every session gate in our UI.

Today the only way in is our web UI. The session graph parks twice before a post is ready: the bundled angle + persona + format gate ([ADR 0029](./0029-angle-persona-bundled-gate.md) / [ADR 0030](./0030-image-format-in-bundled-gate.md)) and the image park ([ADR 0004](./0004-stop-discard-and-image-resume.md) / [ADR 0036](./0036-image-direction-new-script.md)). Confirm is UI-only HTTP ([ADR 0003](./0003-confirm-without-llm.md)).

Target clients are consumer AI apps, which connect from their cloud to a public HTTPS URL. Each customer install already serves the SPA and `/api` from a public `web_base_url`, so no tunnel or hosted gateway is needed. The current MCP spec is `2026-07-28`: stateless core; OAuth 2.1 authorization; Client ID Metadata Documents preferred, Dynamic Client Registration deprecated; Protected Resource Metadata (RFC 9728) mandatory; Tasks and MCP Apps as versioned extensions.

[ADR 0019](./0019-pydantic-ai-inner-harness.md) put "an MCP-server control plane" and "any publish-class tool" out of scope. That ADR covers the **inner** harness, i.e. what our model may call. This ADR adds an **external** surface, i.e. what other apps may call. The publish-tool ban carries over unchanged (§12).

## Decision

### 1. Roles and transport

- Each install is an **MCP server** (OAuth 2.1 resource server) at `{web_base_url}/api/mcp`, Streamable HTTP, spec `2026-07-28`.
- Each install is also its **own authorization server**, issuer = `web_base_url`. No shared identity provider, no hosted gateway.
- External apps are MCP clients. A2A is not offered in this ADR.
- The MCP layer is a thin adapter (`internal/mcp/`) over the existing session service: `run_session_turn`, `choose_angle_turn`, `resume_image_turn`, and Stop. It adds no second turn engine and no graph changes beyond §10.

### 2. Discovery, registration, and the ADR 0006 exception

- Protected Resource Metadata is served at `/.well-known/oauth-protected-resource/api/mcp` (RFC 9728 path insertion). Authorization Server Metadata is served at `/.well-known/oauth-authorization-server` (RFC 8414). A 401 from `/api/mcp` carries `WWW-Authenticate: Bearer resource_metadata=…, scope=…`.
- **ADR 0006 exception:** the spec fixes these well-known paths at the domain root. `web/nginx.conf`, `deploy/azure/nginx/default.conf.template`, and the Vite dev proxy therefore route the `/.well-known/oauth-` prefix to the API. No other API route may live outside `/api`.
- **Client registration:** Client ID Metadata Documents are the primary path. The `client_id` is an HTTPS URL, and we fetch and validate its metadata. Dynamic Client Registration (RFC 7591) is enabled only if a target client still requires it at implementation time; verify each target app before shipping. No pre-registration UI.
- Required protocol checks:
  - PKCE `S256`;
  - exact `redirect_uri` match against the client metadata;
  - an RFC 8707 `resource` parameter, which must equal the MCP URL;
  - `iss` in the authorization response (RFC 9207).

### 3. Consent

- The authorization endpoint lands on a new SPA document route, `/oauth/consent`. That path is outside `/api` and already compliant with ADR 0006.
- Only an **existing account** can log in. Invite-only registration ([ADR 0026](./0026-onprem-first-run-setup.md)) is unchanged, and the connector offers no sign-up.
- The user picks **exactly one** company they are a member of. The page shows the client name, the `client_id` host, and the requested scopes. `images:generate` is shown with an explicit note that it spends the user's token quota.
- Approve and deny go through traditional HTTP (`POST /api/oauth/authorize`). No LLM is involved.

### 4. Grants and tokens

- A new `oauth_grants` table stores `user_id`, `company_id`, `client_id`, `client_name`, `scopes`, `created_at`, `last_used_at`, and `revoked_at`.
- **Access token** — HS256 JWT with these claims:

  | Claim | Value |
  |---|---|
  | `typ` | `"mcp_access"` |
  | `aud` | MCP resource URL |
  | `sub` | user ID |
  | `cid` | company ID |
  | `gid` | grant ID |
  | `scope` | granted scopes |

  The TTL is short. The separate `typ` means a web `access` token cannot call `/api/mcp`, and an MCP token cannot call any other `/api` route (`decode_token(..., TOKEN_TYPE_ACCESS)` already rejects it).
- **Refresh tokens** rotate and are stored hashed, following the existing `refresh_tokens` family pattern.
- **Every MCP request** re-checks four things: the grant is not revoked, the user is active, the membership still exists, and the role is read live (never from the token). Revocation therefore takes effect on the next call.
- `/account` ([ADR 0046](./0046-account-settings-profile.md)) lists the user's connected apps with revoke.
- The token is never passed through to Meta, LLM providers, or any other upstream.

### 5. Scopes

| Scope | Grants | Default request |
|---|---|---|
| `knowledge:read` | `get_brand_context` | yes (`scopes_supported`) |
| `drafts:write` | start / get / choose / revise / cancel drafts | yes (`scopes_supported`) |
| `images:generate` | `approve_image`, and auto mode past the image park | step-up only (403 `insufficient_scope`) |

There is **no scope** for publish or Confirm, the member publish-approval queue ([ADR 0041](./0041-member-usage-limits-and-publish-approval.md)), org catalog propose or approve ([ADR 0011](./0011-knowledge-commit-without-llm.md)), company settings, or members. A client cannot request what does not exist.

### 6. Identity comes from the token only

- No tool accepts `user_id` or `company_id`. The company is always `grant.company_id`, and sessions created over MCP are owned by `sub` in that company.
- Session ownership and the member token cap live in `internal/session/guards.py`, shared by REST routes and the MCP adapter. Copying them is not allowed. Attachment resolution stays route-private because attachments over MCP are out of scope.
- The MCP adapter always passes `company_id=grant.company_id` to `require_owned_session`. A session the same user owns in another company is refused (403), so a grant never reaches beyond its one company. REST omits it and keeps the user-only check.
- Existing rules keep applying unchanged: member token caps (ADR 0041 / 0042), BYOK routing (ADR 0020 / 0021), and the member publish-approval policy at Confirm.

### 7. Tool surface

Request and result shapes live in `schemas/mcp.py` and are exported like other contracts.

| Tool | Scope | Maps to |
|---|---|---|
| `get_brand_context()` | `knowledge:read` | Read-only digest: voice, `roast_level`, product names and one-line summaries. No raw catalog or `search_document` dump. |
| `start_post_draft(brief, context?, auto=false, persona?, image_format?)` | `drafts:write` | Create a session, then the first turn (`run_session_turn`) |
| `get_post_draft(session_id)` | `drafts:write` | Session state: the source of truth for MCP clients |
| `choose_angle(session_id, angle_index \| feedback, persona?, image_format?)` | `drafts:write` | `choose_angle_turn`; `feedback` = the "none fit" (都唔啱) re-brief ([ADR 0028](./0028-angle-pick-before-draft.md) §3) |
| `approve_image(session_id)` | `images:generate` | `resume_image_turn` |
| `revise_post_draft(session_id, instruction)` | `drafts:write` | `POST /messages` semantics, including parked-image revise ([ADR 0036](./0036-image-direction-new-script.md)) |
| `cancel_post_draft(session_id)` | `drafts:write` | Stop ([ADR 0004](./0004-stop-discard-and-image-resume.md)) |

Results carry `status`: `running` | `awaiting_angle_pick` | `awaiting_image_ok` | `ready` | `failed` | `cancelled`. Results **never** include `approval_token`.

### 8. Long turns: return immediately, poll for state

- Mutating tools return `{session_id, status: "running"}` immediately. The turn runs in the API process under the existing turn registry and inherits ADR 0004's single-process limit.
- A second mutating call while a turn is running maps the existing 409 `SessionTurnConflict` to a tool error.
- `get_post_draft` is the source of truth. If a client negotiates the MCP **Tasks** extension, the server MAY return a task handle backed by the same session state, with `tasks/cancel` = `cancel_post_draft`. This mirrors [ADR 0002](./0002-rest-source-of-truth-sse-enhancement.md): the polling baseline must work without Tasks, and Tasks is an enhancement on top.

### 9. Gates with `auto=false`

- A park is a normal tool result:
  - **`awaiting_angle_pick`** returns the angle-park payload: `angles`, `recommended_angle_index`, `personas`, `recommended_persona`, `image_format_options`, `recommended_image_format`.
  - **`awaiting_image_ok`** returns the pending caption and an image-plan summary.
- Tool descriptions tell the client to show the options to its user and relay the answer, unless the user has explicitly delegated the choice.
- The server **cannot distinguish** a human answer from a model answer. Any answer from the client is treated as the user's answer under their grant. This is the amendment to ADR 0029 / 0030: the bundled gate is answered by the client, not necessarily by a human in our UI.

### 10. `auto=true` and `recommended_angle_index`

- **Who answers the gates in auto mode:** the MCP adapter, deterministically with no LLM, using the same service calls a client would make. Graph, gates, Stop, and re-park are unchanged.
  - **Angle:** `recommended_angle_index`, falling back to `0`.
  - **Persona:** the caller's `persona`, else `recommended_persona`.
  - **Format:** the caller's `image_format`, else `recommended_image_format`.
  - **Image park:** the adapter calls `approve_image` if the grant holds `images:generate`. Otherwise the run stops at `awaiting_image_ok`.
- Each gate is auto-answered **at most once** per auto run. A second park of the same kind is returned to the client as an `awaiting_*` result rather than looping. The feedback re-brief is never automated.
- **`brainstormer` gains `recommended_angle_index`** — an int index into `angles`, validated in the node, with an out-of-range value treated as `null`. It is added to `SessionBriefData` and the angle-park payload in `schemas/contracts.py`, and the web angle card pre-selects it. Angle order is unchanged. This is a schema and prompt change under the usual mocked-LLM node tests.

### 11. Provenance

- A new `sessions.origin` JSONB column (Alembic migration) stores `{kind: "mcp", grant_id, client_id, client_name, auto_picks?}`. `auto_picks` records the angle index, persona, format, and whether the image was auto-approved.
- The session list shows a source badge, e.g. 「來自 Claude」 (from Claude). The angle card and preview show auto picks, so the user can revise ([ADR 0036](./0036-image-direction-new-script.md)) or Discard before Confirm.

### 12. Confirm stays in our UI

- A `ready` result carries `preview` (`{caption, hashtags, cta}` + primary image URL) and `confirm_url = {web_base_url}/sessions/{id}`.
- That is a **new SPA deep link**; the SPA has no per-session URL today. It is outside `/api` and compliant with ADR 0006.
- The user reviews the preview there and publishes through the existing Confirm → `POST /api/sessions/{id}/confirm` with `approval_token`. If org policy requires member publish approval, that applies there as today.
- No MCP tool publishes, confirms, approves, or upserts org products. That is [ADR 0003](./0003-confirm-without-llm.md) and [ADR 0011](./0011-knowledge-commit-without-llm.md) applied to the external surface.

### 13. Untrusted input and abuse limits

- `brief` and `context` enter as user-turn content. They are size-capped to `PostMessageRequest` limits and treated as data, not instructions.
- External context is **never a citation source**. Preview source signals stay limited to our signals ([ADR 0045](./0045-honest-citations-preview-identity-sse-h2.md)).
- Per-grant rate limits apply to mutating tools, plus a cap on concurrently running sessions per grant. These are in addition to ADR 0041 token caps.

## Consequences

- Users can draft from Claude or ChatGPT with our voice, catalog, and signals, either fully hands-off (`auto=true`) or by relaying gate choices in the external chat. Publishing is always one click in our UI.
- Each install becomes an OAuth authorization server. New surface: consent page, grants table, token endpoint, metadata endpoints, and client-metadata fetching (SSRF-guarded: HTTPS only, no private ranges, size and time caps).
- The Python MCP SDK becomes a dependency. Pin a version published at least 7 days before adoption.
- ADR 0006 gains its first root-path exception. nginx and Vite configs must route `/.well-known/oauth-` to the API.
- Session guards move out of route-private helpers. REST behaviour must stay identical, covered by existing route tests plus MCP adapter tests.
- `recommended_angle_index` also improves the web card through pre-selection, independent of MCP.
- Auto mode spends the user's token quota without a human looking at each gate. That spend is bounded by the `images:generate` step-up, ADR 0041 caps, and per-grant rate limits.
- Turn execution stays single-process (ADR 0004). Multi-worker MCP needs the same shared turn store that REST would.

## Out of scope

- A2A agent card / remote agent.
- A hosted gateway for firewalled installs.
- Org-level service tokens; grants are per user.
- MCP Apps widgets (an inline angle card in the host).
- Elicitation / Tasks `input_required` for gates.
- File attachments over MCP.
- Any publish-class or approval-class tool.

Each needs its own ADR.
