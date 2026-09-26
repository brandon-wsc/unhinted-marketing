#!/usr/bin/env bash
# Demo / local CD (ADR 0038) — fast-forward this checkout to origin/main and
# rebuild the production on-prem compose stack from that commit.
#
# Same shape as a customer install (SPA + API + migrate, DEPLOYMENT_MODE=onprem)
# but images are built here. This does not pull GitHub Release assets or the
# floating GHCR `onprem` tag. Do not use it to upgrade a versioned install.
#
#   ./deploy/demo-sync.sh
#   ./deploy/demo-sync.sh -f docker-compose.external-db.yml
#
# Run it from a dedicated clone. A dirty tracked tree aborts; deploy/.env is
# ignored by git and is kept. WEB_BASE_URL / CORS_ORIGINS live in that .env.
# A tunnel is only needed when Meta must reach this host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "demo-sync: $ROOT is not a git checkout." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "demo-sync: tracked files are dirty; commit, stash, or reset before updating." >&2
  exit 1
fi

git fetch origin main

if git show-ref --verify --quiet refs/heads/main; then
  git checkout main
  git merge --ff-only origin/main
else
  git checkout -b main --track origin/main
fi

sha="$(git rev-parse --short HEAD)"
echo "demo-sync: building on-prem stack from main @ ${sha}"

cd "$ROOT/deploy"
exec docker compose up -d --build "$@"
