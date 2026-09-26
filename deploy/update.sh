#!/bin/sh
# deploy/update.sh — pull-based updater for self-hosted installs (ADR 0037).
#
# Polls GitHub Releases for the newest tag; on a newer one it dumps the
# bundled Postgres, pins IMAGE_TAG in .env, runs `docker compose pull &&
# up -d` (the one-shot migrate service re-runs `alembic upgrade head`),
# then waits for the api healthcheck. Run it on the Docker host from cron
# or Synology Task Scheduler — GitHub never gets a channel into the host.
#
#   ./update.sh                     update to the latest release tag
#   ./update.sh --check             print current vs latest, change nothing
#   TARGET_TAG=v1.2.3 ./update.sh   pin a specific tag — the rollback path
#
# Env (TARGET_TAG / COMPOSE_FILES may also live in .env):
#   GITHUB_REPO    owner/repo to poll (default: brandon-wsc/unhinted-marketing)
#   COMPOSE_FILES  space-separated compose files; default auto-detects
#                  docker-compose.yml / compose.yaml. e.g.
#                  "docker-compose.yml docker-compose.tunnel.yml" or
#                  "docker-compose.external-db.yml"
#   BACKUP_DIR     pg_dump destination (default: ./backups)
#   HEALTH_TIMEOUT seconds to wait for api healthy (default: 180)

set -eu
cd "$(dirname "$0")"

command -v docker >/dev/null 2>&1 || { echo "update.sh: docker not found" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "update.sh: curl not found" >&2; exit 2; }

GITHUB_REPO=${GITHUB_REPO:-brandon-wsc/unhinted-marketing}
BACKUP_DIR=${BACKUP_DIR:-backups}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

env_get() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -n1 | cut -d= -f2-
}

TARGET_TAG=${TARGET_TAG:-$(env_get TARGET_TAG)}

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a update.log; }

# Space-separated list so one script covers all-in-one / external-db / tunnel.
COMPOSE_FILES=${COMPOSE_FILES:-$(env_get COMPOSE_FILES)}
if [ -z "$COMPOSE_FILES" ]; then
  for f in docker-compose.yml docker-compose.yaml compose.yaml compose.yml; do
    if [ -f "$f" ]; then COMPOSE_FILES=$f; break; fi
  done
fi
if [ -z "$COMPOSE_FILES" ]; then
  echo "update.sh: no compose file found in $PWD" >&2; exit 2
fi

COMPOSE_ARGS=
for f in $COMPOSE_FILES; do
  [ -f "$f" ] || { echo "update.sh: compose file '$f' missing" >&2; exit 2; }
  COMPOSE_ARGS="$COMPOSE_ARGS -f $f"
done
dc() { docker compose $COMPOSE_ARGS "$@"; }

if ! mkdir .update-lock 2>/dev/null; then
  echo "update.sh: already running (.update-lock exists)" >&2; exit 0
fi
trap 'rmdir .update-lock' EXIT INT TERM

# Latest STABLE release only — GitHub's /releases/latest excludes
# prereleases, which is the right default for auto-update. Deploy a beta by
# pinning it: TARGET_TAG=v1.2.3-beta.1 ./update.sh
latest_tag() {
  body=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest") || return 1
  printf '%s\n' "$body" | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1
}

CURRENT=$(env_get IMAGE_TAG)
CURRENT=${CURRENT:-onprem}
TARGET=${TARGET_TAG:-}
if [ -z "$TARGET" ]; then
  if ! TARGET=$(latest_tag); then
    log "release poll failed ($GITHUB_REPO) — no stable release yet, or network/GitHub down"
    exit 1
  fi
fi
[ -n "$TARGET" ] || { log "release tag not found in response"; exit 1; }

if [ "${1:-}" = "--check" ]; then
  log "current=$CURRENT latest=$TARGET files=[$COMPOSE_FILES]"
  exit 0
fi

if [ "$CURRENT" = "$TARGET" ]; then
  log "already on $TARGET"
  exit 0
fi

# Back up the bundled db before pulling — migrate re-runs alembic on `up`,
# and migrations are forward-only. External-DB installs have no `db`
# service here; their Postgres backup is the operator's job.
db_cid=$(dc ps --quiet db 2>/dev/null || true)
if [ -n "$db_cid" ] && [ "$(docker inspect -f '{{.State.Running}}' "$db_cid" 2>/dev/null)" = "true" ]; then
  mkdir -p "$BACKUP_DIR"
  DUMP="$BACKUP_DIR/pre-$TARGET-$(date +%Y%m%d-%H%M%S).sql.gz"
  log "dumping db -> $DUMP"
  dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip >"$DUMP"
  if ! { [ -s "$DUMP" ] && gzip -t "$DUMP" 2>/dev/null; }; then
    log "backup FAILED ($DUMP) — aborting before upgrade"; exit 1
  fi
else
  log "no running db service — skipping dump (external DB: back it up yourself)"
fi

# Pin before pull so compose resolves the release tag, then recreate.
if [ -f .env ] && grep -q '^IMAGE_TAG=' .env; then
  sed "s|^IMAGE_TAG=.*|IMAGE_TAG=$TARGET|" .env >.env.tmp && mv .env.tmp .env
else
  printf 'IMAGE_TAG=%s\n' "$TARGET" >>.env
fi

log "updating $CURRENT -> $TARGET"
dc pull
dc up -d

i=0
while [ "$i" -lt "$HEALTH_TIMEOUT" ]; do
  cid=$(dc ps --quiet api)
  if [ -n "$cid" ]; then
    st=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "")
    if [ "$st" = "healthy" ]; then
      log "api healthy — now on $TARGET"
      exit 0
    fi
    [ "$st" = "unhealthy" ] && break
  fi
  sleep 3
  i=$((i + 3))
done

log "api not healthy within ${HEALTH_TIMEOUT}s — check: docker compose$COMPOSE_ARGS logs api"
log "db migrations may already have run; roll back with TARGET_TAG=$CURRENT ./update.sh (+ restore the dump if the schema moved)"
exit 1
