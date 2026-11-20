# First-run setup

## Sub-features

- `GET /api/setup/status` — unclaimed on-prem instance reports `setup_required: true`
- `POST /api/setup` — claims first user: `201`, platform `superadmin` (`platform_level: 9`), org membership, access token + refresh cookie
- `GET /api/auth/me` — Bearer token resolves to the claimed user
- `POST /api/auth/refresh` — refresh cookie (jar, `Path=/api/auth`) mints a new access token
- `GET /api/setup/status` after — `setup_required` flips to `false`; the instance is sealed

## How to get to it (user POV)

The on-prem wizard at `/setup` in the SPA calls these endpoints; over HTTP it is the first thing any operator does after `docker compose up`. Nothing else exists yet — no users, no org, no sessions.

## Driving it with curl/verify.sh

```bash
.agents/skills/verify-unhinted/scripts/verify.sh drive first-run-setup
```

Asserts each step's status code and the key fields above; writes `evidence/<run-id>/first-run-setup/01..05-*.json` and leaves `state/auth.json` (`access_token`, `company_id`, `email`) for the other drives. Proof is the `201` claim response carrying `platform_level: 9` + a populated `organizations` list, plus the before/after `setup_required` flip — not just a health 200.

## Gotchas

- The drive expects `setup_required == true` on step 1; re-running it against a claimed instance fails fast by design — launch a fresh run.
- `POST /api/auth/register` is invite-only on on-prem after setup (ADR 0026), so this drive must use `/api/setup`, never register.
- Supplying `email_config.smtp_password` in the setup body would need `BYOK_ENCRYPTION_KEY`; the scripted drive omits it, so SMTP stays unverified.
- `verify-pass-*` and the access/refresh tokens in evidence are scoped to the throwaway run — fine to store, useless outside it.
