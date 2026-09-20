# ADR 0033 — Meta Live mode: deauthorize + data-deletion callbacks

- **Status:** Accepted
- **Date:** 2026-09-20
- **Related:** [ADR 0022](./0022-real-publish-instagram.md) (Instagram Login + `social_accounts`), [ADR 0032](./0032-meta-oauth-byo-and-relay.md) (BYO-app default + opt-in relay)

## Context

ADR 0032 shipped the OAuth connect path, but a Meta app stuck in **Development**
mode can only onboard Instagram accounts that hold a role on the app. Flipping
the app to **Live** is the missing step for a normal connect — and Meta refuses
the toggle until the app declares two more endpoints under *Instagram → API
setup with Instagram login* (plus a Privacy Policy URL under App Settings →
Basic, which is config, not code):

- **Deauthorize callback URL** — Meta `POST`s a form `signed_request` when a
  user removes the app from their Instagram settings.
- **Data deletion request URL** — Meta `POST`s the same `signed_request` shape
  when a user asks for their data to be deleted; the endpoint must answer JSON
  `{url, confirmation_code}` where `url` lets the user check the request
  status.

`signed_request` is `<base64url HMAC-SHA256(payload, app_secret)>.<base64url
JSON payload>`; the payload carries `user_id` — the same IG-scoped id we store
as `social_accounts.ig_user_id`.

## Decision

### 1. Two public endpoints on the instance

- `POST /api/social/meta/deauthorize` and
  `POST /api/social/meta/data-deletion` live on the existing public
  `oauth_callback_router` — Meta calls them with no auth, like the OAuth
  callback. The signature **is** the authentication: a bad or missing
  `signed_request` is a 400, so the endpoints can only disconnect an account
  Meta itself identifies.
- Both verify against the snapshot `meta_app_secret` (BYO mode) and delete
  **every** `social_accounts` row for that `ig_user_id` — deleting is
  idempotent and doubles as the honest data deletion: the only data we hold
  keyed to the IG user is the stored token + linkage (sessions/drafts belong
  to the org, not the IG identity). A user_id we never saw is a no-op 200.
- Data deletion responds `{url, confirmation_code}` synchronously. The
  confirmation code is **stateless** — `base64url({u,t}).HMAC_SHA256(jwt_secret)`
  — and `GET /api/social/meta/data-deletion/{code}` reports `completed`
  because deletion already happened before we answered Meta. No new table.

### 2. URLs are derived, shown read-only — same rule as the OAuth callback

- BYO: `{web_base_url}/api/social/meta/deauthorize` and
  `{web_base_url}/api/social/meta/data-deletion`. Relay: the fixed vendor
  URLs `{relay}/meta/deauthorize` / `{relay}/meta/data-deletion`.
- `GET …/social-accounts/oauth/status` gains `deauthorize_url` /
  `data_deletion_url`, and `GET /api/instance/settings` gains
  `meta_oauth_deauthorize_url` / `meta_oauth_data_deletion_url` — the admin
  copies exact strings, nothing hand-typed.

### 3. Relay forwards platform events to the owning install

Meta only calls the **vendor** app, so in relay mode the instance never sees a
`signed_request` it could verify (it has no app secret). The Worker:

- writes `TICKETS["u:{ig_user_id}"] = instance_id` (90-day TTL) when it issues
  a connect ticket, giving it a user→install routing table;
- verifies `signed_request` with the vendor secret, then `POST`s
  `{base}/api/social/meta/relay` with
  `{kind: "deauthorize"|"data_deletion", ig_user_id, sig}` where
  `sig = HMAC_SHA256(key: instance_id, msg: "{kind}:{ig_user_id}")` — the
  registry slug doubles as a per-install shared secret, so no new config;
- for `data_deletion` proxies the instance's `{url, confirmation_code}`
  back to Meta; with no mapping (connect predates this ADR) it answers a
  static "relay stores no data" status URL itself.

**Accepted limit:** `instance_id` appears in browser-visible OAuth `state`, so
the relay signature only proves "the relay said so" — a caller who saw a
connect URL could disconnect that install's IG accounts. Impact is
self-DoS-class (no token exposure); a per-install secret column in REGISTRY is
the hardening path if needed.

## Consequences

- Going Live needs no more code: paste the two URLs + a Privacy Policy URL in
  the dashboard and flip the toggle. App Review / Business Verification are
  still unneeded for own-brand Standard Access.
- Deleting a `social_accounts` row on deauthorize means a deauthorized org
  flips to `not_connected` on its own — no stale-token publish attempts.
- Unauthenticated-write surface grows by three routes; all are signature-gated
  and only ever delete, never read or write token material out.
- A superseding ADR is required to persist deletion requests, change the
  relay forward signature, or move these endpoints behind auth.
