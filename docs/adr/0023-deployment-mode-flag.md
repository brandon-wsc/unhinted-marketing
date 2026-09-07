# ADR 0023 — Deployment mode flag (cloud vs on-prem), baked at build/start

- **Status:** Accepted
- **Date:** 2026-09-07
- **Supersedes:** —
- **Related:** [ADR 0006](./0006-api-path-prefix-and-spa-proxy.md) (API prefix / SPA proxy), [ADR 0010](./0010-org-membership-invites-and-shared-assets.md) (on-prem as a target environment)

## Context

The product will ship in two shapes: a hosted **cloud** SaaS and a self-hosted
**on-prem** deployment (Docker). Until now nothing in the codebase distinguished
them — `APP_ENV` (development/production) is about *hardening*, not *where the
deployment runs*. Upcoming behavior needs to branch on the deployment shape
(e.g. hosted email backend vs link-only invites, billing, telemetry), so we need
a flag with one hard property: **once a deployment is built/started, the mode
never changes.** A runtime toggle invites half-migrated state (an org created
under `cloud` rules suddenly served by `onprem` code paths).

Prior art: GitLab CE/EE and Mattermost treat edition/deployment mode as a
boot-time constant — changing it means redeploying, never flipping mid-process.

## Decision

### 1. One flag, two values

`deployment_mode: "cloud" | "onprem"`, default **`onprem`** (self-hosted safe
default — a deployment that forgets to configure anything behaves like the
conservative self-hosted build, matching ADR 0010's link-mode invite default).

### 2. Backend: startup constant

`Settings.deployment_mode` (`internal/config.py`, env `DEPLOYMENT_MODE`) is read
once when the process starts and is treated as immutable for the process
lifetime. Changing it requires a restart. Python has no compile step, so for
on-prem the "build-time" guarantee comes from the Docker image: the root
`Dockerfile` takes `ARG DEPLOYMENT_MODE=onprem` → `ENV`, baking the mode into
the image; cloud images build with `--build-arg DEPLOYMENT_MODE=cloud`.

### 3. Frontend: Vite build-time substitution

`web/src/lib/deployment.ts` reads `import.meta.env.VITE_DEPLOYMENT_MODE`, which
Vite substitutes at `vite build` — the mode is compiled into the bundle and
cannot change at runtime. Unknown/unset values fall back to `onprem`. The
`web/Dockerfile` bakes it via `ARG VITE_DEPLOYMENT_MODE=onprem`.

### 4. `GET /api/meta` as the runtime source of truth

Unauthenticated endpoint returning `{ deployment_mode, app_env, version }`
(`schemas/meta.py`). The SPA can read the backend's mode at boot instead of
trusting only its own bundle — the two are built separately and could drift.
When they disagree, the **backend** wins (it owns the behavior that matters:
publishing, invites, billing).

### 5. No behavior branches yet

This ADR introduces the flag and plumbing only. Any feature that branches on
`deployment_mode` should say so in its own ADR/STATUS entry.

## Consequences

- Mode changes are redeploys, not config flips — by design.
- On-prem deployers get `onprem` even if they set nothing; cloud infra must set
  `DEPLOYMENT_MODE=cloud` explicitly (build ARG or env).
- Two images per release (`onprem` default, `cloud` variant) for both `api` and
  `web`; the only difference is the baked flag.
- `GET /api/meta` is public; it must never grow sensitive fields — mode, env
  name, and version only.
