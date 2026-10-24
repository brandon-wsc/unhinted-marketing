# ADR 0053 — Advertise CIMD; allow any port on http loopback redirects

- **Status:** Accepted
- **Date:** 2026-10-24
- **Supersedes:** —
- **Amends:** [ADR 0051](./0051-remote-mcp-server.md) §2 (authorization-server metadata must advertise Client ID Metadata Documents; `redirect_uri` match gains the RFC 8252 loopback-port exception, including `localhost`)

## Context

ADR 0051 made each install its own OAuth 2.1 authorization server and chose Client ID Metadata Documents over Dynamic Client Registration. The metadata document at `/.well-known/oauth-authorization-server` already advertised PKCE `S256`, the authorize and token endpoints, and `token_endpoint_auth_methods_supported: ["none"]`. It did not advertise `client_id_metadata_document_supported: true`, and it did not expose `registration_endpoint`.

MCP 2026-07-28 tells clients to try CIMD when the authorization server advertises that flag, and to fall back to Dynamic Client Registration otherwise. Claude's connector docs are stricter: Claude selects CIMD only when the metadata has **both** `client_id_metadata_document_supported: true` and `"none"` in `token_endpoint_auth_methods_supported`. If either is missing, Claude tries DCR. A live check on 2026-10-24 against `https://sergiusw.synology.me/api/mcp` showed the result: `claude mcp add` then `claude mcp list` failed with "Incompatible auth server: does not support dynamic client registration." Grok's published client (`https://grok.com/oauth/mcp-client.json`, fetched the same day) is also a public CIMD client (`token_endpoint_auth_method: none`) and hits the same missing-flag wall. Neither client needs us to add DCR.

The second failure shows up once a client is forced onto Claude Code's CIMD (`https://claude.ai/oauth/claude-code-client-metadata`). That document, fetched 2026-10-24, lists only:

```json
"redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"]
```

`claude mcp login` then sends `redirect_uri=http://localhost:<ephemeral-port>/callback`. ADR 0051's exact string match rejects the port (`400 redirect_uri not in client metadata`). The same request with `http://localhost/callback` (no port) reaches `/oauth/consent`. RFC 8252 §7.3 requires an authorization server to accept any port on a loopback **IP literal**. Claude's own connector docs say to apply that port-agnostic match to `localhost` as well, because the CLI sends the name, not `127.0.0.1`. RFC 8252 §8.3 still discourages `localhost`; we accept it because that is the redirect Claude Code sends.

Grok's redirect URIs are ordinary `https` callbacks (`https://grok.com/connectors-oauth-exchange-code/` and `https://console.x.ai/connectors-oauth-exchange-code/`). They stay on exact match. Hosted Claude (`https://claude.ai/api/mcp/auth_callback`) does too.

## Decision

1. **Advertise CIMD. Do not add DCR.** Authorization-server metadata includes `client_id_metadata_document_supported: true` and keeps `token_endpoint_auth_methods_supported: ["none"]`. There is still no `registration_endpoint`. PKCE `S256` and the RFC 8707 `resource` check are unchanged.
2. **Loopback port exception, nothing else.** `redirect_uri` stays an exact string match against the CIMD `redirect_uris`, except when both the registered URI and the requested URI are `http` loopback redirects that share host, path, and query. The port may differ, including a registered URI that already names a port. The hosts that qualify are exactly `localhost`, `127.0.0.1`, and `[::1]` (compressed or expanded). They are not aliases: a registration for `127.0.0.1` does not allow `localhost`, and `::ffff:127.0.0.1` is not `127.0.0.1`. Other addresses in `127.0.0.0/8` do not qualify.
3. **What still has to match on a loopback URI.** Scheme (`http` only — `https://localhost` stays exact), host, path, and query. Userinfo, fragments, backslashes, and CR/LF never take the exception. A different path, a trailing slash, or a different query is a mismatch.
4. **The issued code stays bound to the concrete URI.** The authorization code stores the `redirect_uri` the client sent (the ephemeral port included). The token request must present that same string. The port exception is not re-applied at the token endpoint, so a code minted for one port cannot be redeemed on another.
5. **SSRF / CIMD fetch guards are unchanged.** Loopback is legal as a client's redirect target. It is still rejected as a `client_id` we would fetch.

## Consequences

- A fresh Claude Code install can discover CIMD from metadata and does not need `--client-id` or a `registration_endpoint`. `claude mcp login` can pass the authorize `redirect_uri` check for `http://localhost:<port>/callback` and `http://127.0.0.1:<port>/callback`.
- Grok can present `client_id=https://grok.com/oauth/mcp-client.json` without DCR. Its https callbacks still have to match the CIMD document exactly, trailing slash included.
- A local process can bind the loopback port and receive the redirect. That is the RFC 8252 native-app tradeoff; PKCE `S256` still binds the code to the client that started the flow. The consent page already shows the client name and the `client_id` host (ADR 0051 §3). This ADR does not add a separate loopback warning.
- Non-loopback redirects, including every `https` callback, keep exact string match. No prefix, wildcard, or port substitution.
