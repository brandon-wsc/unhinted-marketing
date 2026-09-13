# ADR 0026 — On-prem first-run setup, invite-only register, DB instance settings

- **Status:** Accepted
- **Date:** 2026-09-13
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (`DEPLOYMENT_MODE` branches behavior), [ADR 0005](./0005-platform-roles.md) (platform ladder; first user lands at `SUPERADMIN=9`), [ADR 0025](./0025-db-storage-config-and-portal-migration.md) (env-seeds-DB pattern reused for instance settings), [ADR 0020](./0020-org-byok-keys-models-routing.md) (Fernet-at-rest for the SMTP password)

## Context

A self-hosted install boots with zero users and an open `POST /auth/register`
that granted every caller a solo org at `platform_level=3`. There was no
first-run flow: the operator had to register, then promote themselves via CLI
(`set-platform-role`), and registration stayed open to anyone who could reach
the instance — wrong for invite-only on-prem.

Peer self-hosted products (GitLab, Metabase, n8n, PostHog, Mattermost, Ghost)
converge on one shape: the **first user is the admin**, a one-time wizard
collects the admin account + instance/org name + base URL, integrations
(SMTP, LLM) are optional and skippable, and a persisted "setup complete"
marker keeps the wizard from reappearing.

## Decision

### 1. `instance_settings` singleton row is the deployment source of truth

One row (`id = 1`, CHECK-enforced) holds:

- `setup_completed_at` — NULL = wizard pending (on-prem)
- `web_base_url` — invite links, OAuth redirect fallback, local media URLs
- email delivery: `email_backend` (`link`/`smtp`/`console`), `email_from`,
  `smtp_host/port/user`, `smtp_password_encrypted` (BYOK Fernet KEK,
  last4-only in responses), `smtp_tls`

Env vars (`WEB_BASE_URL`, `EMAIL_*`, `SMTP_*`) **seed** the row on boot when
absent (same pattern as ADR 0025 `storage_configs`). After seeding they are
fallback-only — the portal row wins. The migration marks deployments that
already have users as setup-complete so existing installs never see the
wizard.

`internal.instance.config` publishes an in-process snapshot (8s TTL). Sync
readers inside SSE emit paths (`resolve_stored_url`, invite links) call
`get_snapshot()` and fall back to env values when the cache is cold — they
must not await a DB load.

### 2. First-run setup claims the only SUPERADMIN

- `GET /api/setup/status` — public; `{deployment_mode, setup_required,
  web_base_url}`. The payload does **not** report env credentials — the
  wizard treats the environment as opaque.
- `POST /api/setup` — on-prem only (404 on cloud), rate-limited like
  register. Row is locked `FOR UPDATE`; a completed row returns 409, so the
  first-user claim cannot race. One request creates the user
  (`platform_level=9`), the first company org (`owner` membership), applies
  `web_base_url` + optional email config, and stamps `setup_completed_at`.
- `GET /api/instance/settings` — platform `ADMIN+` read.
- `PUT /api/instance/settings` — `SUPERADMIN`-only write; `smtp_password`
  rotates only when a non-empty value is sent and is never returned.

The SPA `/setup` wizard runs account+org → instance URL/email (skippable
fields) → optional LLM provider (org BYOK, skippable) → done. Setup marks
the deployment sealed; `useSetup` flips and normal routes take over.

### 3. On-prem register is invite-only after setup

`POST /auth/register` gains `invite_token`. On `DEPLOYMENT_MODE=onprem`:

- setup pending → `403 setup_required` (SPA routes to `/setup`)
- setup complete, no/invalid/expired invite or email mismatch →
  `403 invite_required`

Invite acceptance semantics are unchanged — the invitee's bootstrap solo org
is replaced on `POST /invites/{token}/accept`. Cloud registration is
untouched: open, no invite required.

The login page hides the register link on on-prem unless the visitor carries
an invite (`?next=/invite/{token}`); the register page redirects on-prem
non-invite visitors to `/login` (or `/setup` when pending).

### 4. Non-blocking integrations

LLM keys and SMTP are deliberately optional in the wizard: an install is
usable (invites via `link` mode) without either. The wizard never inspects
env credentials — each optional step is skipped manually, no "already set
via env" hints.

## Consequences

- First boot on on-prem shows `/setup`; the first human becomes
  `SUPERADMIN` and seeds the first org — no CLI promotion needed.
- Invite links, media public URLs, OAuth redirects, and invite emails all
  read the DB-backed instance URL — changing it in **System → Instance**
  takes effect within the snapshot TTL, no restart.
- Anyone hitting an on-prem instance post-setup cannot self-register; access
  is invite-only by design. Cloud behavior is unchanged.
- `smtp_password` joins BYOK keys under the Fernet KEK — rotating
  `BYOK_ENCRYPTION_KEY` still breaks stored secrets (same as ADR 0020).
- A second `POST /setup` can never mint another superadmin; privilege
  changes afterwards stay with existing admin tooling.
