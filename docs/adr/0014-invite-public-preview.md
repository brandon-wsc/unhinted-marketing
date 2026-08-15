# ADR 0014 — Public invite preview (email + company name)

- **Status:** Accepted
- **Date:** 2026-08-15
- **Amends:** [ADR 0010](./0010-org-membership-invites-and-shared-assets.md) §2 (unregistered invitees / accept still email-bound)

## Context

ADR 0010 binds accept to the invited email (mismatch → 403) and has no anonymous accept. The SPA therefore told people to register or log in with that email, but **did not pre-fill it** — there was no public preview API, by design (token in the URL was treated as opaque).

That forces the invitee to re-type the address. A typo creates a second account, then 403 on accept. The token is already a capability secret (single-use, 7-day, hash-stored); hiding the bound email after the link is opened does not add meaningful protection, and it is the main source of mismatch errors.

## Decision

`GET /api/invites/{token}` is **public** (no auth). For a **pending** invite (not expired, revoked, or accepted) it returns:

```text
{ email, company_name }
```

It does **not** return `role`, `company_id`, inviter identity, or the raw token. Invalid / expired / revoked / used tokens → **400** with the same generic detail as accept (`Invalid or expired invite`) — no extra enumeration.

Accept rules are unchanged: still email-bound (403), still auth-required `POST …/accept`. Preview exists so the UI can **lock** the email on login/register (`readOnly`) and omit the register "company name" field when `?next=/invite/:token` (bootstrap org is still created server-side and replaced on accept per [ADR 0013](./0013-invite-accept-replaces-bootstrap-org.md)).

The invite-accept page may show `email` and `company_name` in copy. Token in the URL remains the secret; preview does not weaken hash-at-rest.

## Consequences

- Schema: `OrgInvitePreviewResponse` in `schemas/company.py`; OpenAPI refresh via `python -m scripts.export_contracts`.
- UI spec: [knowledge/UI.md](../knowledge/UI.md) (logged-out + login/register prefill). Previously "no public company-name preview" is superseded for this payload only.
- Tests: API coverage for 200 (no auth), 400 (unknown / expired / revoked / used); web locks email when preview succeeds.
- Later: do not grow this payload (no roster, no role) without a new ADR.
