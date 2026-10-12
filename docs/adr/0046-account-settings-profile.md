# ADR 0046 — Account settings page + self-service profile

## Status

Accepted

## Context

`users.display_name` was write-once: set at `POST /api/auth/register` (and the on-prem first-admin `POST /api/setup`), with no API or UI to change it afterwards. There was also no user-level settings surface — `/settings` is company-scoped (voice, products, members, …) and the header user menu only carries language/theme/logout. A profile belongs at account level, not inside company settings, and a one-off menu dialog is too thin for what will grow (password change, sessions, notification prefs).

## Decision

- New user settings page at `/account`, reachable from the header user menu (`帳戶` / Account entry, next to 公司設定). First panel: **Profile** — editable `display_name`, read-only email, joined date, org memberships.
- `PATCH /api/auth/me` accepts `UserUpdate { display_name }` (1–120 chars, whitespace-trimmed, blank rejected) and returns the full `UserResponse`. Bearer-authenticated, self-service only — a user patches their own row; admins do not rename members via this route (org member management stays role/limit only, per ADR 0010/0041).
- `display_name` stays global to the user — one name across all org memberships; there is no per-org nickname.
- Read-time name lookups (member lists, publish-approval `requested_by_name`) show the new name immediately, including on historical rows. Approval reviewer identity remains the stored `reviewed_by_email` snapshot; we accept live display-name lookup rather than snapshotting names into receipts.
- `/account` is the home for future user-level settings (password change, active sessions); company settings stays org-scoped.

## Consequences

- Members and approval history always render the current display name; point-in-time audit of "who was this named then" is not available (email remains stable).
- Rename is HTTP-only and outside the session graph — no LLM involvement, consistent with confirm/publish boundaries.
- New account-level settings get a dedicated surface instead of leaking into company settings or accumulating dialogs on the user menu.
