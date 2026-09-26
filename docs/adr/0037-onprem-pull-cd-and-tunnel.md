# ADR 0037 — On-prem CD: pull-based image updates + Cloudflare Tunnel exposure

- **Status:** Accepted
- **Date:** 2026-09-26
- **Supersedes:** —
- **Related:** [ADR 0027](./0027-docker-deploy-packages.md) (compose packages + release artifacts), [ADR 0023](./0023-deployment-mode-flag.md) (baked mode), [ADR 0032](./0032-meta-oauth-byo-and-relay.md) / [ADR 0033](./0033-meta-live-mode-platform-callbacks.md) / [ADR 0034](./0034-relay-per-install-shared-secret.md) (relay needs a public instance URL)

## Context

The release pipeline already does the vendor half of CD: every `v*` tag builds multi-arch `unhinted-{api,web}` images to GHCR and attaches standalone compose assets to the GitHub Release. What was missing is the install half — how a running self-hosted instance (e.g. a NAS) learns about and applies a new release, and how it is exposed to the internet safely.

Two constraints shape the design:

1. **The repo is public.** A self-hosted GitHub Actions runner on the install host is an RCE channel — any fork PR can land code on the runner unless runner groups and environment gates are configured perfectly. Any other push channel (webhook listener, SSH from CI) needs either an inbound port or a stored credential on the host.
2. **Public HTTPS is required anyway.** The OAuth relay redirects the user's browser to `<instance>/api/social/oauth/relay-finish`, and forwards Meta platform callbacks (deauthorize, data-deletion) server-to-server to `<instance>/api/social/meta/relay` (ADR 0032/0033). A LAN-only install cannot complete Meta Live-mode requirements.

## Decision

### 1. Pull-based updates only — no channel from GitHub to the host

`deploy/update.sh` runs on the Docker host under cron / Synology Task Scheduler. It polls `api.github.com/.../releases/latest`; on a newer tag it:

1. Dumps the bundled `db` via `pg_dump` into `backups/` (skipped for external-DB installs — their Postgres is backed up by the operator).
2. Pins `IMAGE_TAG` in `.env` — the deploy is versioned, not floating.
3. `docker compose pull && up -d` — the one-shot `migrate` service re-runs `alembic upgrade head` before `api`/`scheduler` start (ADR 0027).
4. Waits for the `api` healthcheck. Failure leaves logs and a warning — **no auto-rollback**, because migrations are forward-only; rollback is `TARGET_TAG=<prev> ./update.sh` plus a dump restore if the schema moved.

`TARGET_TAG` overrides the poll (pin / rollback). `--check` reports current vs latest without changing anything. `COMPOSE_FILES` selects the compose shape, so the same script covers all-in-one, external-DB, and tunneled stacks.

### 2. Exposure = Cloudflare Tunnel, added as a compose override

`deploy/docker-compose.tunnel.yml` adds a token-managed `cloudflared` service; the tunnel's public hostname points at `http://web:80` inside the compose network (nginx already proxies `/api`, so one hostname covers SPA + API + SSE). Outbound only: no port-forwarding, no inbound firewall rules, the host IP is never published, edge TLS is free. `WEB_BIND=127.0.0.1` keeps the web port off the LAN so the tunnel is the only ingress.

The bundled `db` still publishes no host port; nothing else in the stack is reachable through the tunnel by construction.

### 3. No blanket edge auth (e.g. Cloudflare Access) in front of the app

Meta platform callbacks arrive at the instance server-to-server via the relay and carry no Access credential — a blanket Access policy would 302 them to an OTP page. Access with path bypasses for `/api/social/meta/*` + `/api/social/oauth/*` remains possible but splits the security model; the default posture is: app-level JWT auth (unchanged), edge WAF managed rules, and rate-limiting on auth endpoints. Revisit if an install wants a private-by-default posture.

### 4. Release assets grow two files

`release.yml` also attaches `update.sh` and `compose.tunnel.yaml` (verbatim copy of the override — it carries no `build:` section) so standalone installs get the updater and tunnel without a repo checkout.

## Consequences

- Update lag = poll interval; the operator owns timing. Boot/upgrade behavior is unchanged — `migrate` still runs inside `up`.
- The updater pins `IMAGE_TAG`; anyone running `docker compose up -d` by hand afterwards gets the pinned release, not a surprise floating-tag move. Explicit `IMAGE_TAG`/`IMAGE_PREFIX` env overrides still win on a manual command.
- A bad release that fails the health gate is *migrated but not serving* — recovery is `TARGET_TAG` pin-back plus optional dump restore. The pre-update dump makes the worst case a restore, not data loss.
- Anonymous GHCR pulls still require the one-time package-visibility flip documented in `deploy/README.md`.
- `COMPOSE_FILES` including the tunnel override means `update.sh` pulls `cloudflared` too; its image is tag-pinned, bumped deliberately with the repo.
