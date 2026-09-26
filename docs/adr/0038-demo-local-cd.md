# ADR 0038 — Demo / local CD tracks `main`; customer installs stay on Releases

- **Status:** Accepted
- **Date:** 2026-09-26
- **Supersedes:** —
- **Related:** [ADR 0023](./0023-deployment-mode-flag.md) (on-prem mode baked at image build), [ADR 0027](./0027-docker-deploy-packages.md) (compose packages + GHCR release assets)

## Context

Two audiences share the same production compose shape (`APP_ENV=production`,
`DEPLOYMENT_MODE=onprem`, SPA + API + `migrate`) and must not share an update
mechanism.

Customer self-hosted installs are versioned. `.github/workflows/release.yml`
runs on `v*` tags, pushes `ghcr.io/<owner>/unhinted-{api,web}` with that
version **and** the floating `onprem` tag, and attaches pull-only compose
assets to the GitHub Release. `docker compose pull` and those assets move
when a release is published. They do not move when `main` moves.

A personal machine or a private demo host needs the opposite: always run
**current `main` HEAD** so stakeholder demos match what just landed, still in
the on-prem deploy package (local `docker compose up -d --build` from
`deploy/`). Folding that into Release polling, the floating `onprem` tag, or
a customer updater would either ship unreleased `main` to customer installs
or leave demo hosts sitting on the last tag.

## Decision

### 1. Two tracks, two mechanisms

| Track | Source of truth | Update |
|-------|-----------------|--------|
| **Customer pull CD** | A published GitHub Release and its GHCR tags | Release assets, or `docker compose pull` of a version tag / floating `onprem` |
| **Demo / local CD** | `origin/main` in a git checkout | Fast-forward that checkout, then `docker compose up -d --build` from `deploy/` |

Demo images are built from the checkout. `DEPLOYMENT_MODE=onprem` and
`VITE_DEPLOYMENT_MODE=onprem` stay the compose build args (ADR 0023). The
floating GHCR `onprem` tag is not the demo source.

### 2. Helper stays on the demo track

`deploy/demo-sync.sh` fetches `origin/main`, fast-forwards (no merge), and
runs `docker compose up -d --build`. Extra arguments are passed through
(`-f docker-compose.external-db.yml` for the external-DB package). It refuses
a dirty tracked tree so a cron job cannot clobber local edits. Ignored files
such as `deploy/.env` are left in place.

The script does not download Release assets, does not `docker compose pull`
the floating tag, and does not poll GitHub Releases.

### 3. Do not merge the tracks

A customer updater (release poll, pinned `IMAGE_TAG`, standalone compose from
a Release) must not `git checkout main` or rebuild unpublished source.
`demo-sync.sh` must not be documented or invoked as the way to upgrade a
versioned install. `release.yml` stays tag-triggered; it does not build
`main` for demo hosts.

Do not add `deploy/update.sh`, or any other Release poller, that
fast-forwards to `main`. Customer pull CD stays on GitHub Releases and GHCR
tags. Demo / local CD stays on `demo-sync.sh`.

## Consequences

- Operators who want latest `main` use a dedicated clone and `demo-sync.sh`
  (or the same git + `--build` steps by hand). See [deploy/README.md](../../deploy/README.md).
- Customer install docs stay on the Release curl / pull flow (ADR 0027).
- `WEB_BASE_URL` / `CORS_ORIGINS` still come from `deploy/.env`. A tunnel is
  only required when Meta must reach the host (Instagram Login or real
  publish). Localhost demos keep the compose default `http://localhost:8484`.
- Env `WEB_BASE_URL` seeds `instance_settings` on first boot only; afterwards
  System → Instance wins (ADR 0026).
