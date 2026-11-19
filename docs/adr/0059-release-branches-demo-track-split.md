# ADR 0059 — Release branches off `main`; hosted demo on releases, NAS/local on `main`

- **Status:** Accepted
- **Date:** 2026-11-19
- **Supersedes:** —
- **Related:** [ADR 0027](./0027-docker-deploy-packages.md) (compose packages + GHCR release assets), [ADR 0037](./0037-demo-local-cd.md) (demo/local CD — demo-track scope narrowed here), [ADR 0044](./0044-azure-aca-demo.md) (hosted Azure demo)

## Context

`main` has been both the integration branch and the line releases are tagged
from. That worked pre-1.0, but customer installs now pull versioned GHCR
images (ADR 0027) and the v1.0 line is approaching — we need a way to patch
a shipped `vX.Y.*` line while `main` keeps moving, without a permanent
git-flow `develop` branch.

The two "demo" audiences also want different freshness: the public hosted
demo (`demo.unhinted.hk`, ADR 0044) should show the latest stable release,
while the NAS test host and local checkouts want `main` HEAD.

## Decision

### 1. `main` stays the only standing integration branch

- Feature / fix / chore work branches off `main` and PRs back to `main` —
  unchanged. No `develop` branch: tags already give "customers pull stable",
  and a second long-lived branch would add a merge hop to every PR while
  forcing a rewrite of every "branch off latest `main`" convention.

### 2. `release/vX.Y` branches are cut on demand

- Cut from `main` (or retroactively from a tag:
  `git branch release/v1.0 v1.0.0`) only when the line needs it — release
  hardening/soak, or the first patch to a shipped `vX.Y.*`.
- `vX.Y.Z` tags are made on the release branch when one exists, otherwise on
  `main`. `release.yml` is tag-triggered, so either source publishes the
  same GHCR + Release assets.
- Hotfix flow: `hotfix/<slug>` branch off the release branch → PR into
  `release/vX.Y` → tag the patch release → merge or cherry-pick the fix
  back to `main` so it is not lost.
- Delete a release branch once the line is end-of-life; there is no standing
  fleet of them.

### 3. Three update tracks, explicit

| Track | Host / audience | Source of truth | Update |
|-------|-----------------|-----------------|--------|
| Hosted demo | `demo.unhinted.hk` (Azure ACA, ADR 0044) | Latest published release | `release.yml` `demo` job — pins the `v*` tag on all ACA apps/jobs and re-runs migrate; `azd up` stays as the manual path |
| Demo / local CD | NAS test host, personal machines | `origin/main` HEAD | `deploy/demo-sync.sh` (ADR 0037) |
| Customer pull CD | Versioned self-hosted installs | A published GitHub Release | Release assets / `docker compose pull` |

ADR 0037's "demo tracks `main`" now applies to the NAS/local track only.
The hosted demo was already on release images (`IMAGE_TAG` defaults to the
floating `onprem` tag); this ADR makes that the explicit stable track and
`release.yml`'s `demo` job automates the upgrade — a `v*` tag updates all
five ACA resources to the pinned tag and starts the migrate job. The job
pins `vX.Y.Z` rather than `onprem` because an unchanged image string
produces no new ACA revision (so `onprem` would not re-pull); a later
manual `azd up` returns the apps to `onprem` — the same image — so the
drift is cosmetic. Azure auth is GitHub OIDC on the `unhinted-deploy`
environment (no
stored client secret); one-time setup is in `deploy/azure/README.md`.

### 4. CI covers release branches

`ci.yml` runs on pushes to `release/**` in addition to `main`, so
hardening and hotfix commits get the same gates. The PR conventions job
already accepts `release/` and `hotfix/` head branches.

## Consequences

- Unhardened releases keep the simple flow: tag `main`, done.
- Branch protection for `release/*` should mirror `main` (GitHub repo
  settings — a manual step, like `main`'s).
- `AGENTS.md` branch conventions and `deploy/README.md` document the
  lifecycle and the three tracks.
- Every `v*` tag now deploys the hosted demo automatically — including
  `workflow_dispatch` re-publishes of an old tag, which roll the demo
  back to that version.
- Cherry-picking a fix back to `main` is a human step; forgetting it ships
  the fix to customers but regresses it on the next minor line.
