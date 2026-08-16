# ADR 0010 — Org membership management, invite links, shared-asset scope

- **Status:** Accepted
- **Date:** 2026-08-11
- **Supersedes:** — (unblocks K6 promote-to-org Approvals, held in STATUS since 2026-08-10)
- **Amended by:** [ADR 0013](./0013-invite-accept-replaces-bootstrap-org.md) (§4: bootstrap solo-org replace on accept); [ADR 0014](./0014-invite-public-preview.md) (§2: public preview of bound email + company name)

## Context

Multi-tenant bootstrap shipped with auth: register auto-creates an `entities` (type `company`) row + an `organization_members` owner row, and `require_company_access` / `require_company_settings_editor` (`internal/auth/org.py`) already gate voice and products. But there is **no way to add a second human to an org** — no member CRUD, no invite flow — so "share company assets with my team" is impossible. Products (`owner_scope = org | user`) and voice are already shared; K6 (promote Mine → Org) is explicitly held until this org-system cleanup lands.

On-prem deployment is a target environment, so any invite flow that *requires* hosted email (Resend/SES) is a non-starter.

## Decision

### 1. Member management API under the company resource

All routes gated by existing org guards; manager = owner/admin (`COMPANY_SETTINGS_EDITOR_ROLES` reused):

| Method | Route | Who | Notes |
|--------|-------|-----|-------|
| GET | `/api/companies/{id}/members` | any member | user id, name, email, role, joined_at |
| PATCH | `/api/companies/{id}/members/{user_id}` | owner/admin | change role **`admin` ↔ `member` only** — never set `owner` via this route |
| DELETE | `/api/companies/{id}/members/{user_id}` | owner/admin, or self (leave) | sole-owner protected |
| PATCH | `/api/companies/{id}` | owner/admin | **rename only** (`name` / display fields) — not voice/products (those stay on their own routes) |

**Exactly one `owner` per org (MVP).** Register creates that owner. Invites may only create `admin` or `member` (not `owner`). PATCH cannot promote anyone to `owner` or demote the sole owner → **409**. Ownership transfer is a **later ADR** (not in this MVP).

### 2. Invites = DB token; delivery is pluggable

New table `org_invites`: `id`, `organization_id` (FK, cascade), `email` (normalized lower/strip), `role` (`admin` \| `member` only), `token_hash` (SHA-256, same discipline as `refresh_tokens` — raw token never persisted), `invited_by` (FK users, SET NULL), `expires_at` (7 days), `accepted_at`, `revoked_at`.

**Constraints:** at most one **pending** invite per `(organization_id, email)` (unique partial index where `accepted_at` / `revoked_at` are null). Re-invite after revoke/expiry creates a new row (or replaces pending).

| Method | Route | Who | Notes |
|--------|-------|-----|-------|
| POST | `/api/companies/{id}/invites` | owner/admin | body `{email, role}`; response **always includes `invite_url`**; rate-limit create |
| GET | `/api/companies/{id}/invites` | owner/admin | pending invites |
| DELETE | `/api/companies/{id}/invites/{invite_id}` | owner/admin | revoke |
| GET | `/api/invites/{token}` | public | pending invite only; `{ email, company_name }` — [ADR 0014](./0014-invite-public-preview.md) |
| POST | `/api/invites/{token}/accept` | authed user whose email matches invite | validates hash, expiry, not-revoked; marks `accepted_at`, creates membership |

Invite tokens are **single-use, 7-day expiry, bound to the invited email** (accepting account's email must match after normalize; mismatch → 403). Revoking an invite does not affect already-accepted memberships — use member DELETE.

**Unregistered invitees:** there is no anonymous accept. Flow is: open invite link → if not logged in, **register or login with the invited email** → then accept. SPA invite page must guide that path (copy must not imply click-once join without an account).

`WEB_BASE_URL` is required to build `invite_url` even when `EMAIL_BACKEND=link`.

### 3. Email delivery: pluggable backend, link-mode default

New `internal/notify/` module with a `send_invite_email(...)` seam and config-driven backends:

| `EMAIL_BACKEND` | Behavior |
|---|---|
| unset / `link` | No email; UI shows the invite URL for admin to copy (WhatsApp/Slack). Default — always works on-prem |
| `smtp` | Send via env-configured relay (`SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS`, `EMAIL_FROM`, `WEB_BASE_URL`); response still includes `invite_url` as fallback |
| `console` | Dev — logs the email |

This mirrors GitLab/Gitea-style self-hosted practice: the deployer points the app at *their* SMTP relay; the app knows nothing about providers. The same seam is reused later for password reset / notifications. Hosted-SaaS can add a Resend/SES backend without touching call sites.

### 4. MVP: one user ↔ one org

A user may belong to **at most one org**. Invite accept → 409 if the user already has a membership — **except** the register-bootstrap solo org, which accept replaces ([ADR 0013](./0013-invite-accept-replaces-bootstrap-org.md)). The frontend's `user.organizations[0]` assumption (`company-settings.tsx`, session pages) is therefore valid for MVP — **no org switcher**. Multi-org is a later ADR if needed.

### 5. Shared-asset scope: products + voice only

Shared across the org: **org-scope products** and **company voice** (status quo). Everything else stays **user-private** (owned by `sessions.user_id`): chat history, preview media/images, drafts. Session listing/access stays scoped to the owning user (audit session routes while landing this). Teammates see each other only via the members list — they do **not** browse another member's sessions.

### 6. Revocation is immediate; per-request checks only

`require_company_access` already queries membership per request — no caching. Removing a member immediately cuts access to **company resources** (products, voice, settings, invites) on the next request. Their own sessions (rows keyed by `user_id`) still exist in the DB, but any path that requires company membership will **403**. No JWT/session-token revocation needed; refresh tokens stay user-global. This closes the STATUS hardening item "re-check org membership on session access after revoke" by making it an invariant, not a TODO.

### 7. Role semantics unchanged for publishing

Settings write stays owner/admin (existing). **Confirm/publish stays open to all org members** for MVP — small-team marketing tool; only the session owner has that draft, and Confirm is still gated by `approval_token` per revision (ADR 0003). Revisit a publish-role gate together with K6 Approvals if real teams ask for it.

## Consequences

- One Alembic revision: `org_invites` table (+ pending unique index). No change to `users` / `organization_members` schema beyond using existing roles.
- New API shapes go through `schemas/` (per AGENTS.md) + `python -m scripts.export_contracts`; `UserResponse` unchanged (memberships already exposed).
- New `internal/notify/` seam; SMTP path uses async sending off the request path (background task), failures logged and non-fatal — the `invite_url` in the response is the always-works fallback.
- Web: new **Members** tab in `/settings` (list, invite form showing copy-link, role dropdown admin/member, remove) + company rename; invite accept route with register/login guidance; i18n keys in `zh-HK` / `en`.
- Register flow unchanged (still auto-creates org + sole owner); invite accept is the only second path into an org.
- CI: member/invite API tests mock the email backend — no SMTP server, no secrets.
- Unblocks **K6** promote-to-org Approvals (the "share my asset with the org" UX) as the next knowledge slice. Knowledge commit-without-LLM remains **ADR 0011**; formal product-retrieve tenant ADR (behavior already shipped K3–K4) is deferred as **ADR 0012** if still wanted.
- Later (not now): multi-org + switcher, **ownership transfer**, multi-owner, publish role gate, audit log, seats/billing, email-change flows.
