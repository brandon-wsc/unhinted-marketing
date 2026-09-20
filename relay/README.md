# unhinted-oauth-relay (Cloudflare Worker)

ADR 0032 §3 — the single Meta-whitelisted OAuth callback that fans out to
on-prem installs on customer domains. Meta Strict Mode requires exact-match
redirect URIs and the list is dashboard-only, so one fixed URI
(`{RELAY_BASE}/meta/callback`) serves every install.

## Flow

```
instance (relay mode)          this Worker               Meta              instance
POST /oauth/start  →  authorization_url:
                      {RELAY}/authorize?state={iid}:{row}:{blob}
                  →   validates iid ∈ REGISTRY
                  →   302 instagram.com/oauth/authorize
                      (injects vendor client_id + own redirect_uri)
                      Meta → GET /meta/callback?code&state
                  →   REGISTRY[iid] → base URL
                  →   POST api.instagram.com/oauth/access_token
                  →   GET  graph.instagram.com/access_token (long-lived)
                  →   GET  graph.instagram.com/v{v}/me
                  →   TICKETS[ticket] = payload (60s TTL)
                  →   302 {base}/api/social/oauth/relay-finish?ticket&state
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
| `GET /authorize?state=…` | Instance OAuth start target — 302s to Instagram with vendor creds |
| `GET /meta/callback` | Meta redirect target (whitelisted URI) |
| `GET /ticket/{uuid}` | One-time redeem — read-once, 60s TTL |
| `GET /healthz` | Smoke check |

## Setup

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

The install's `meta_oauth_instance_id` is auto-generated and shown read-only
under **System → Instance** (relay mode). Register it:

```bash
npx wrangler kv key put --namespace-id <REGISTRY_ID> "<instance_id>" "https://marketing.acme.com"
```

The value must be the install's public base URL — the Worker 302s the browser
to `{base}/api/social/oauth/relay-finish`.

## On the instance

1. System → Instance → OAuth mode = **relay**, paste the relay base URL
   (or set env `OAUTH_RELAY_URL` before first boot — it seeds the row).
2. Register `meta_oauth_instance_id` in REGISTRY (above).
3. Company settings → Instagram → Connect.
