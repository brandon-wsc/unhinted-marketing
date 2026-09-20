# unhinted-oauth-relay (Cloudflare Worker)

ADR 0032 §3 — the single Meta-whitelisted OAuth callback that fans out to
on-prem installs on customer domains. Meta Strict Mode requires exact-match
redirect URIs and the list is dashboard-only, so one fixed URI
(`{RELAY_BASE}/meta/callback`) serves every install.

## Flow

```
instance (relay mode)          Meta                      this Worker              instance
POST /oauth/start  →  authorize URL:
                      redirect_uri={RELAY}/meta/callback
                      state={instance_id}:{row_id}:{blob}
user authorizes   →   GET /meta/callback?code&state
                                                  →  REGISTRY[instance_id] → base URL
                                                  →  POST api.instagram.com/oauth/access_token
                                                  →  GET  graph.instagram.com/access_token (long-lived)
                                                  →  GET  graph.instagram.com/v{v}/me
                                                  →  TICKETS[ticket] = payload (60s TTL)
                                                  →  302 {base}/api/social/oauth/relay-finish?ticket&state
                                                                            →  GET {RELAY}/ticket/{id}
                                                                               (redeem + delete)
                                                                            →  upsert social_accounts
```

- **Transit-only**: the app secret lives here (`wrangler secret put`), tokens
  pass through but are never logged or persisted beyond the ticket TTL.
- **No open redirect**: destinations come only from `REGISTRY` — `state` chooses
  *which* registered instance, never an arbitrary URL.
- Registry is a manual allowlist for v1 (`wrangler kv key put`); a self-serve
  registration flow is a later decision (license key / activation).

## Endpoints

| Route | Purpose |
|---|---|
| `GET /meta/callback` | Meta redirect target (whitelisted URI) |
| `GET /ticket/{uuid}` | One-time redeem — read-once, 60s TTL |
| `GET /healthz` | Smoke check |

## Setup

```bash
scripts/setup-oauth-relay.sh   # wizard: account → URL → KV → secret → Meta whitelist → deploy → register
```

Manual equivalent:

```bash
cd relay
npm install
npx wrangler login
npx wrangler kv namespace create REGISTRY   # paste id into wrangler.toml
npx wrangler kv namespace create TICKETS    # paste id into wrangler.toml
npx wrangler secret put META_APP_SECRET     # Instagram App Secret
# META_APP_ID goes in wrangler.toml [vars]; whitelist {base}/meta/callback in Meta
npx wrangler deploy
```

## Register an install

```bash
npx wrangler kv key put --namespace-id <REGISTRY_ID> "<instance_id>" "https://marketing.acme.com"
```

`instance_id` must match the id the on-prem backend puts at the front of
OAuth `state` (`{instance_id}:{row_id}:{blob}`) — the backend exposes it under
System → Instance once the relay slice lands.

## Pending backend slice (not in this worker)

- `meta_oauth_mode=relay` on `instance_settings` + `OAUTH_RELAY_URL`
- `start_oauth` relay path: `redirect_uri={relay}/meta/callback`, state prefixed
  with the instance id
- `GET /api/social/oauth/relay-finish` — verify state+CSRF cookie, redeem the
  ticket, upsert `social_accounts` (same as the BYO callback)
- UI disclosure on the ready caption ("routed via the Unhinted connect service")
