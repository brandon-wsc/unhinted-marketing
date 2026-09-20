# ADR 0032 — On-prem Meta OAuth: BYO-app default + opt-in hosted relay

- **Status:** Accepted
- **Date:** 2026-09-20
- **Related:** [ADR 0022](./0022-real-publish-instagram.md) (Instagram Login connect + `social_accounts`), [ADR 0023](./0023-deployment-mode-flag.md) (cloud vs on-prem), [ADR 0025](./0025-db-storage-config-and-portal-migration.md) (env-seeds-DB pattern), [ADR 0026](./0026-onprem-first-run-setup.md) (`instance_settings` singleton; callback derives from `web_base_url`), [ADR 0020](./0020-org-byok-keys-models-routing.md) (Fernet-at-rest reused for the app secret)
- **Research:** internal survey of self-hosted products (Postiz, Mixpost, Chatwoot, Cal.com, n8n, GitLab, Discourse, Supabase, Appsmith, Documenso, Activepieces, VS Code, better-auth) against primary docs

## Context

An on-prem install lives on a customer-owned domain. Meta enforces Strict Mode:
`redirect_uri` must be an **exact** entry in the app's Valid OAuth Redirect URIs —
no wildcards, no extra query params except `state`, and the list is editable only
by hand in the App Dashboard (no API). A vendor-owned Meta app therefore cannot
serve arbitrary customer domains: the connect flow fails at the authorize dialog.

The industry survey shows two patterns in the wild:

- **BYO-app** is the default — Postiz, Mixpost, Chatwoot, Cal.com, n8n, GitLab,
  Discourse, Supabase all make self-hosters register their own provider app. It is
  cheaper than assumed: Meta grants **Standard Access** (no App Review, no
  Business Verification) when the app only serves IG professional accounts the
  owner has added to the app. Review is only forced for agency/multi-client use.
- **Vendor-hosted relay** exists and ships — Activepieces `CLOUD_OAUTH2` (default
  even on self-hosted), VS Code `vscode.dev/redirect`, better-auth `oAuthProxy`,
  Njia. Meta's own Login Security doc prescribes the mechanism: pass the dynamic
  part through `state` to a limited set of whitelisted redirect URIs.

The hard constraint: `POST api.instagram.com/oauth/access_token` requires
`client_secret`, so with a vendor-owned app either the secret ships inside every
on-prem image (a distributed secret is a public secret — impersonation + one
revocation kills all customers) or the token exchange runs on vendor
infrastructure (tokens transit our servers — transit-only, not zero-knowledge).

## Decision

### 1. On-prem defaults to BYO Meta app; cloud keeps the vendor app

One Meta app per deployment. Credentials move to the `instance_settings`
singleton row (ADR 0026), following the `smtp_password` pattern:

- `meta_app_id` (plain), `meta_app_secret_encrypted` (BYOK Fernet KEK,
  `meta_app_secret_last4` only in API responses).
- Env `META_APP_ID` / `META_APP_SECRET` **seed** the row on boot when absent;
  after seeding the portal wins (same rule as `WEB_BASE_URL` / `SMTP_*`).
- `GET /api/instance/settings` exposes `meta_app_id`, `meta_app_secret_last4`,
  and the derived callback URL; `PUT` stays SUPERADMIN-only, and the secret
  rotates only when a non-empty value is sent.
- The callback URI is **not** a field — it stays derived:
  `{web_base_url}/api/social/oauth/callback`. The UI shows it read-only with a
  copy affordance so the admin whitelists exactly that string in the Meta
  dashboard (same reason `META_OAUTH_REDIRECT_URI` was dropped — a second source
  can only drift).

### 2. Guided setup lives in the Instagram settings panel

- `GET …/social-accounts/oauth/status` gains `configured` + `callback_url` so the
  panel renders an explicit not-configured state (steps + copyable callback URL)
  instead of letting Connect fail. `meta_oauth_not_configured` becomes a mapped,
  actionable error, not a raw code.
- Panel copy must state that connecting an IG account the operator owns/manages
  needs only **Standard Access — no Meta App Review** — otherwise users assume a
  review queue and give up. Agency/multi-client installs are the segment that
  needs Advanced Access; that is where §3 earns its keep.
- Manual token paste (`PUT …/social-accounts/{platform}`) stays the escape hatch
  for installs that cannot or will not run OAuth.

### 3. Opt-in vendor relay — Cloudflare Worker + one-time tickets

- `instance_settings` gains `meta_oauth_mode`: `byo` (default) | `relay`,
  `meta_oauth_relay_url` (defaults to the hosted relay — a fixed product
  endpoint, read-only in the portal; env `OAUTH_RELAY_URL` only overrides to a
  self-hosted/dev relay), and
  `meta_oauth_instance_id` (generated at seed — the REGISTRY slug).
  Relay is **opt-in only** and disclosed in the UI — never a silent default
  (Appsmith's backlash).
- The relay is a **Cloudflare Worker** (`relay/` in this repo): Workers Secrets
  hold the vendor app secret, two KV namespaces provide `REGISTRY`
  (instance_id → base URL) and `TICKETS` (one-time payloads).
- Protocol:
  1. `POST /oauth/start` in relay mode returns
     `{relay}/authorize?state={instance_id}:{row_id}:{blob}` — the Worker
     validates the `instance_id` prefix against REGISTRY, then 302s to
     `instagram.com/oauth/authorize` injecting the vendor `client_id` and its
     own fixed `redirect_uri` (`{relay}/meta/callback`, whitelisted once on the
     vendor app). The instance never sees vendor creds.
  2. Meta redirects to `{relay}/meta/callback`; the Worker runs the same
     exchange as BYO (short → long-lived → `/me` → professional + publish-scope
     checks), stores the result under a UUID in `TICKETS` (60s TTL), and 302s
     to `{REGISTRY[instance_id]}/api/social/oauth/relay-finish?ticket&state`.
  3. `relay-finish` re-validates pending state + the double-submit CSRF cookie
     exactly like the BYO callback, redeems the ticket server-to-server
     (read-once delete), verifies `payload.instance_id` matches this install,
     then upserts `social_accounts` identically.
- Destinations come only from the server-side registry — raw `state` never
  supplies a URL (open redirect + code leak). v1 registration is a manual
  `wrangler kv key put` allowlist; self-serve registration is deferred.
- Exchange placement is **relay-side**: the app secret never leaves vendor
  infrastructure. Accepted cost — tokens transit vendor infra (transit-only,
  TTL-bound, never logged). Shipping the secret inside every on-prem image is
  rejected (public secret, single-point revocation). Zero-trust customers stay
  on BYO.
- Known limit: KV `get` + `delete` is not atomic — two racing redeems could
  both read a live ticket. Impact is bounded (60s TTL, only the instance
  redeems, upsert is idempotent); a Durable Object swap is the hardening path
  if replay becomes a concern.

## Consequences

- Cloud deployments are unchanged; on-prem admins manage Meta creds in System →
  Instance with no restart (snapshot TTL), matching `web_base_url`.
- `meta_app_secret` joins BYOK keys and `smtp_password` under the Fernet KEK —
  rotating `BYOK_ENCRYPTION_KEY` breaks it the same way (ADR 0020).
- Connect UX on an unconfigured on-prem install is a guided card, not an error —
  the panel needs the new `oauth/status` fields before it can render it.
- Relay phase later adds a vendor-operated dependency for opt-in installs only;
  already-connected tokens are unaffected by relay downtime.
- A superseding ADR is required to change the BYO-default posture, portal
  credential storage, or the relay's opt-in/exchange-placement rules; guided
  copy and UI arrangement may iterate without one.
