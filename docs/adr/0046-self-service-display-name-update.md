# ADR 0046 — Self-service display name update

## Status

Accepted

## Context

`users.display_name` was write-once: set at `POST /api/auth/register` (and the on-prem first-admin `POST /api/setup`), with no API or UI to change it afterwards. A typo at signup or a name change meant editing the database by hand. There is no user-settings page; account-level surface is the header user menu (org-level fields live under `/settings`, which is company-scoped).

## Decision

- `PATCH /api/auth/me` accepts `UserUpdate { display_name }` (1–120 chars, whitespace-trimmed, blank rejected) and returns the full `UserResponse`. Bearer-authenticated, self-service only — a user patches their own row; admins do not rename members via this route (org member management stays role/limit only, per ADR 0010/0041).
- `display_name` stays global to the user — one name across all org memberships; there is no per-org nickname.
- Read-time name lookups (member lists, publish-approval `requested_by_name`) show the new name immediately, including on historical rows. Approval reviewer identity remains the stored `reviewed_by_email` snapshot; we accept live display-name lookup rather than snapshotting names into receipts.
- UI: a rename dialog opened from the header user menu (both dropdown and mobile-dialog surfaces). No user-settings page is introduced for a single field.

## Consequences

- Members and approval history always render the current display name; point-in-time audit of "who was this named then" is not available (email remains stable).
- Rename is HTTP-only and outside the session graph — no LLM involvement, consistent with confirm/publish boundaries.
