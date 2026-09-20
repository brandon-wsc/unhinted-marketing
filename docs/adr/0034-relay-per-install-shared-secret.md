# ADR 0034 — Relay per-install shared secret (ticket + event signing)

- **Status:** Accepted
- **Date:** 2026-09-20
- **Supersedes:** [ADR 0032](./0032-meta-oauth-byo-and-relay.md) §3 REGISTRY value shape and ticket redemption; [ADR 0033](./0033-meta-live-mode-platform-callbacks.md) §3 event-signature key
- **Related:** [ADR 0020](./0020-org-byok-keys-models-routing.md) (Fernet-at-rest reused for the shared secret)

## Context

ADR 0032's relay protocol uses `meta_oauth_instance_id` for two jobs: the
REGISTRY routing slug **and** the only secret-ish value on the path. But the
slug travels in plaintext `state` — it appears in the authorize URL any org
member's browser receives, in browser history, and in System → Instance. Two
gaps follow:

- **Bearer ticket.** `GET /ticket/{uuid}` returns a live long-lived IG token to
  anyone holding the URL. The only defenses are UUID entropy and the 60s TTL —
  a leaked redirect (TLS proxy log, extension, shared-device history) redeems
  inside the window.
- **Forgeable platform events.** `POST /api/social/meta/relay` authenticates
  with `HMAC(instance_id, …)` — a caller who learns the slug can disconnect
  this install's IG accounts at will.

## Decision

### 1. REGISTRY value becomes `{url, secret}` — a per-install shared secret

Each registered install gets an independent shared secret issued at
registration time (v1 stays a manual step — the setup wizard generates it):

```bash
wrangler kv key put --namespace-id <REGISTRY_ID> "<instance_id>" \
  '{"url":"https://marketing.acme.com","secret":"<issued-secret>"}'
```

Bare-string entries are **rejected** (fail closed — re-register in the new
shape). The admin pastes the issued secret into System → Instance:
`meta_oauth_relay_secret` is a write-only `PUT /api/instance/settings` field
stored Fernet-encrypted (`meta_oauth_relay_secret_encrypted` +
`meta_oauth_relay_secret_last4`, same pattern as `meta_app_secret`).
`OAUTH_RELAY_SECRET` env seeds it on boot while unset (dev/UAT convenience).

### 2. Ticket redemption is authenticated

`GET /ticket/{id}?sig={hmac}` where `sig = HMAC-SHA256(secret, "ticket:{id}")`
(hex). The Worker reads the ticket, resolves the payload's `instance_id` to
its REGISTRY secret, and constant-time-compares before returning the payload.
A bad or missing `sig` gets 403 **without deleting the ticket** — probing can
neither redeem nor burn someone else's ticket. The `instance_id` match on the
instance side (`meta_oauth.py`) stays as a second layer.

### 3. Platform-event signatures key on the secret

`relay_event_signature` becomes `HMAC-SHA256(secret, "{kind}:{ig_user_id}")`
— identical shape to ADR 0033, keyed by the shared secret instead of the
public slug. An install with no secret configured rejects all relayed events
(`meta_oauth_invalid_signed_request`).

### 4. Registry URLs must be https

The Worker validates `new URL(entry.url).protocol === "https:"` when reading
REGISTRY (`http:` tolerated only for loopback dev hosts). A hand-maintained
allowlist typo can no longer send tokens over plaintext.

### 5. Data-deletion only claims "completed" when nothing exists to delete

The relay's static data-deletion answer applies only when no `u:{ig_user_id}`
routing entry exists. When a mapping exists but the forward fails (instance
down, non-2xx, de-registered), the relay answers 503 so Meta retries —
previously it silently reported completion while the install still held data.

## Consequences

- `meta_oauth_instance_id` reverts to a pure public routing slug — knowing it
  grants nothing.
- `oauth_configured()` in relay mode now also requires the shared secret —
  Connect stays in the guided not-configured state until registration
  completes instead of starting a doomed flow.
- Secret rotation = re-register the REGISTRY entry + paste the new secret;
  no token or account migration needed.
- Installs registered before this ADR must re-register (`{url, secret}` JSON)
  — the Worker fails closed on legacy bare-string values.
- The KV get+delete ticket race noted in ADR 0032 is unchanged; the Durable
  Object hardening path still applies if replay becomes a concern.
