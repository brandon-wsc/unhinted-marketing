# ADR 0055 — Self-service change password (verify current first)

## Status

Accepted

## Context

Users cannot change their own password. A forgotten password means an admin reset (or, on-prem, direct DB surgery), and there is no self-service path even when the user still knows the current password. [ADR 0046](./0046-account-settings-profile.md) already reserved `/account` as the home for user-level settings and named password change as the first follow-up. Any change-password flow that only trusts the UI to have collected the current password would let a hijacked session (stolen access token, unattended browser) silently take over the account — the current password must be re-proved server-side before a new one is accepted.

## Decision

- Two new bearer-authenticated routes on the existing auth router, outside the session graph (HTTP-only, no LLM — same boundary as confirm/publish):
  - `POST /api/auth/me/verify-password` with `VerifyPasswordRequest { password }` — step 1. Verifies against the stored hash; `200 { message: "ok" }` or `401 "Current password is incorrect"`. Rate-limited under the shared auth limiter (`verify_password` bucket, per-client sliding window like register/login/refresh).
  - `POST /api/auth/me/password` with `ChangePasswordRequest { current_password, new_password }` — step 2. The server **re-verifies** `current_password` before saving (the verify step is not a granted capability, just UX), rejects `new_password` shorter than 8 characters (same rule as register) and `new_password == current_password`, then re-hashes (Argon2 via `pwdlib`) and saves. `200 { message: "Password changed" }`. Rate-limited (`change_password` bucket).
- Verification is **not** a capability grant: there is no server-side "unlocked" state or token between step 1 and step 2. The two-step split exists so the UI can collect the current password once and then gather + confirm the new one; every change request still stands alone with both passwords.
- Web `/account` gets a **Password** panel next to Profile with a two-step flow: step 1 collects the current password and calls verify-password (a wrong current password is a field error, not just client gating); step 2 unlocks new password + confirm fields and submits both to change-password. Client checks reuse the register-time i18n error keys (`errors.passwordTooShort`, `errors.passwordMismatch`); server messages map through `map-api-error.ts`.
- Existing sessions stay valid after a password change (access JWTs are stateless; refresh-token families are not rotated by this route). Scope is the self-service path only — an admin-side "reset member password" flow remains out of scope.
- No DB migration: `users.password_hash` is rewritten in place.

## Consequences

- A stolen-session attacker can still change the password if they know the current one; if they don't, verify/change fail closed. We accept that the UI "unlock" is cosmetic — the server re-check makes step 2 safe on its own.
- Rate limiting is per client IP on the shared auth limiter, so an authenticated user probing their own password hits the same window as login attempts. Redis-backed limiting remains future work (MVP note in the limiter module).
- Contract mirrors regenerate via `python -m scripts.export_contracts` (OpenAPI picks up both routes).
