#!/bin/bash
# verify-unhinted — launch an isolated API+Postgres stack, drive real HTTP
# user journeys, and capture evidence. Usage:
#
#   verify.sh launch              # fresh pg + migrated DB + uvicorn
#   verify.sh doctor              # is this instance worth driving?
#   verify.sh drive <feature>     # first-run-setup | session-workspace
#   verify.sh cleanup             # stop api + pg, keep evidence/
#
# Env: VERIFY_RUN_ID (pick a run; default = newest), VERIFY_API_PORT (8871),
# VERIFY_PG_PORT (55432), VERIFY_PG_ADMIN_DSN (shared-pg admin DSN),
# OPENAI_API_KEY / LLM_* / TAVILY_API_KEY / BYOK_ENCRYPTION_KEY pass through
# to the API process when set (LLM-gated features need them).

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"
RUNS_DIR="$SKILL_DIR/runs"
EVIDENCE_DIR="$SKILL_DIR/evidence"

API_PORT="${VERIFY_API_PORT:-8871}"
PG_PORT="${VERIFY_PG_PORT:-55432}"
ADMIN_DSN="${VERIFY_PG_ADMIN_DSN:-postgresql://postgres:postgres@127.0.0.1:5432/postgres}"
PG_IMAGE="pgvector/pgvector:pg18"
BASE="http://127.0.0.1:${API_PORT}"

PY="$REPO_ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
UVICORN="$REPO_ROOT/.venv/bin/uvicorn"; [ -x "$UVICORN" ] || UVICORN=uvicorn
ALEMBIC="$REPO_ROOT/.venv/bin/alembic"; [ -x "$ALEMBIC" ] || ALEMBIC=alembic

die() { echo "verify: $*" >&2; exit 1; }

need_run() {
  local d
  if [ -n "${VERIFY_RUN_ID:-}" ]; then
    d="$RUNS_DIR/$VERIFY_RUN_ID"
  else
    d="$(ls -1d "$RUNS_DIR"/*/ 2>/dev/null | tail -1 | sed 's:/$::')"
  fi
  [ -n "$d" ] && [ -f "$d/run.env" ] || die "no run found — launch first"
  echo "$d"
}

pg_sql() { # $1 = SQL on the maintenance database
  "$PY" - "$ADMIN_DSN" "$1" <<'PY'
import asyncio, sys, asyncpg
async def main():
    conn = await asyncpg.connect(sys.argv[1], timeout=10)
    try:
        await conn.execute(sys.argv[2])
    finally:
        await conn.close()
asyncio.run(main())
PY
}

pg_probe() {
  "$PY" - "$ADMIN_DSN" <<'PY' >/dev/null 2>&1
import asyncio, sys, asyncpg
async def main():
    conn = await asyncpg.connect(sys.argv[1], timeout=3)
    await conn.close()
asyncio.run(main())
PY
}

pg_wait() { # $1 = app DSN (postgresql+asyncpg://...) — real connect, not pg_isready
  local dsn="$1"
  for _ in $(seq 1 60); do
    "$PY" - "$dsn" <<'PY' >/dev/null 2>&1 && return 0
import asyncio, sys, asyncpg
async def main():
    conn = await asyncpg.connect(sys.argv[1].replace("+asyncpg", ""), timeout=2)
    await conn.close()
asyncio.run(main())
PY
    sleep 1
  done
  die "postgres never accepted connections at $dsn"
}

cmd_launch() {
  local run_id="v$(date +%Y%m%d-%H%M%S)"
  local run="$RUNS_DIR/$run_id"
  mkdir -p "$run/state/media" "$EVIDENCE_DIR/$run_id"

  lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >/dev/null 2>&1 \
    && die "port $API_PORT already listening — set VERIFY_API_PORT"

  local mode="" container="" dbname="" db_url=""
  if pg_probe; then
    mode="shared"
    dbname="unhinted_verify_$(echo "$run_id" | tr -cd 'a-z0-9')"
    pg_sql "CREATE DATABASE \"$dbname\"" \
      || die "postgres reachable at $ADMIN_DSN but CREATE DATABASE failed"
    db_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/$dbname"
  else
    command -v docker >/dev/null 2>&1 || die "no postgres at $ADMIN_DSN and no docker cli"
    docker info >/dev/null 2>&1 || die "no postgres at $ADMIN_DSN and docker daemon down — start Docker Desktop or: docker compose up -d db"
    mode="container"
    container="unhinted-verify-pg-$run_id"
    dbname="unhinted_verify"
    docker run -d --rm --name "$container" \
      -p "127.0.0.1:$PG_PORT:5432" \
      -e POSTGRES_USER=verify -e POSTGRES_PASSWORD=verify \
      -e POSTGRES_DB="$dbname" "$PG_IMAGE" >/dev/null \
      || die "docker run failed (port $PG_PORT busy? set VERIFY_PG_PORT)"
    db_url="postgresql+asyncpg://verify:verify@127.0.0.1:$PG_PORT/$dbname"
    pg_wait "$db_url"
  fi

  (cd "$REPO_ROOT" && DATABASE_URL="$db_url" "$ALEMBIC" upgrade head) \
    >"$run/alembic.log" 2>&1 || die "alembic upgrade head failed — see $run/alembic.log"

  cat >"$run/api.env" <<EOF
DATABASE_URL=$db_url
JWT_SECRET=verify-$run_id-signing-key-not-for-production
APP_ENV=development
DEPLOYMENT_MODE=onprem
API_HOST=127.0.0.1
API_PORT=$API_PORT
WEB_BASE_URL=http://127.0.0.1:$API_PORT
CORS_ORIGINS=http://127.0.0.1:$API_PORT
MEDIA_ROOT=$run/state/media
PUBLISH_ADAPTER=stub
EMAIL_BACKEND=link
AUTH_RATE_LIMIT_ENABLED=false
INVITE_RATE_LIMIT_ENABLED=false
BYOK_PROBE_RATE_LIMIT_ENABLED=false
REFRESH_COOKIE_SECURE=false
EOF
  local v
  for v in OPENAI_API_KEY LLM_API_BASE LLM_CHEAP_MODEL LLM_MEDIUM_MODEL \
           LLM_STRONG_MODEL LLM_IMAGE_MODEL BYOK_ENCRYPTION_KEY TAVILY_API_KEY; do
    [ -n "${!v:-}" ] && echo "$v=${!v}" >>"$run/api.env"
  done

  (cd "$REPO_ROOT" && set -a && . "$run/api.env" && set +a \
    && exec "$UVICORN" cmd.api.main:app --host 127.0.0.1 --port "$API_PORT") \
    >"$run/api.log" 2>&1 &
  echo $! >"$run/api.pid"

  local i up=""
  for i in $(seq 1 60); do
    curl -fsS "$BASE/api/health" >/dev/null 2>&1 && { up=1; break; }
    sleep 1
  done
  [ -n "$up" ] || die "api never answered /api/health — see $run/api.log"
  local status
  status="$(curl -fsS "$BASE/api/setup/status")" \
    || die "api up but /api/setup/status failed — DB not ready; see $run/api.log"
  echo "$status" | jq -e 'has("setup_required")' >/dev/null \
    || die "unexpected /api/setup/status body: $status"

  cat >"$run/run.env" <<EOF
RUN_ID=$run_id
MODE=$mode
CONTAINER=$container
DB_NAME=$dbname
DB_URL=$db_url
API_PORT=$API_PORT
PG_PORT=$PG_PORT
BASE=$BASE
EOF
  echo "launched run $run_id"
  echo "  api:  $BASE  (pid $(cat "$run/api.pid"), log $run/api.log)"
  echo "  pg:   $mode ${container:-$dbname}"
  echo "  next: $0 doctor && $0 drive first-run-setup"
}

cmd_doctor() {
  local run; run="$(need_run)"; . "$run/run.env"
  local pid alive=false port_owner=false pg_ok=false health_ok=false db_ok=false
  pid="$(cat "$run/api.pid" 2>/dev/null || echo 0)"
  kill -0 "$pid" 2>/dev/null && alive=true
  lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN 2>/dev/null \
    | awk -v p="$pid" '$2==p {f=1} END{exit !f}' && port_owner=true
  if [ "$MODE" = "container" ]; then
    [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ] && pg_ok=true
  else
    pg_probe && pg_ok=true
  fi
  curl -fsS "$BASE/api/health" 2>/dev/null | jq -e '.status=="ok"' >/dev/null 2>&1 && health_ok=true
  curl -fsS "$BASE/api/setup/status" 2>/dev/null | jq -e 'has("setup_required")' >/dev/null 2>&1 && db_ok=true

  mkdir -p "$EVIDENCE_DIR/$RUN_ID"
  jq -n --arg run "$RUN_ID" --arg pid "$pid" --arg mode "$MODE" \
        --argjson alive "$alive" --argjson port_owner "$port_owner" \
        --argjson pg_ok "$pg_ok" --argjson health_ok "$health_ok" \
        --argjson db_ok "$db_ok" \
    '{run_id:$run, api_pid:($pid|tonumber), pg_mode:$mode,
      api_pid_alive:$alive, api_owns_port:$port_owner, pg_reachable:$pg_ok,
      health_ok:$health_ok, db_query_ok:$db_ok}' \
    | tee "$EVIDENCE_DIR/$RUN_ID/doctor.json"
  $alive && $port_owner && $pg_ok && $health_ok && $db_ok
}

JAR="" TOKEN="" HTTP_BODY="" HTTP_CODE="" EDIR=""
http() { # http METHOD PATH [JSON]
  local args=(-sS -X "$1" -H "Content-Type: application/json" -o "$HTTP_BODY" -w '%{http_code}')
  [ -n "$JAR" ] && args+=(-b "$JAR" -c "$JAR")
  [ -n "$TOKEN" ] && args+=(-H "Authorization: Bearer $TOKEN")
  [ -n "${3:-}" ] && args+=(--data "$3")
  HTTP_CODE="$(curl "${args[@]}" "$BASE$2")"
}

save() { # save NN-name — record status + parsed (or raw) body under $EDIR
  mkdir -p "$EDIR"
  if jq -e . "$HTTP_BODY" >/dev/null 2>&1; then
    jq -n --argjson code "$HTTP_CODE" --slurpfile body "$HTTP_BODY" \
      '{http_status:$code, body:$body[0]}' >"$EDIR/$1.json"
  else
    jq -n --argjson code "$HTTP_CODE" --rawfile body "$HTTP_BODY" \
      '{http_status:$code, raw_body:$body}' >"$EDIR/$1.json"
  fi
}

expect() { [ "$HTTP_CODE" = "$1" ] || die "$2 (got HTTP $HTTP_CODE — see $EDIR)"; }

drive_setup() {
  local run="$1"; EDIR="$EVIDENCE_DIR/$RUN_ID/first-run-setup"
  JAR="$run/state/cookies.txt"; TOKEN=""
  local email="verify-$RUN_ID@example.com"

  http GET /api/setup/status; save 01-status-before
  expect 200 "setup/status"
  jq -e '.body.setup_required == true' "$EDIR/01-status-before.json" >/dev/null \
    || die "setup_required is not true — instance already claimed? relaunch on a fresh run"

  http POST /api/setup "{\"email\":\"$email\",\"password\":\"verify-pass-$RUN_ID-123\",\"display_name\":\"Verify Bot\",\"organization_name\":\"Verify Org\"}"
  save 02-setup; expect 201 "POST /api/setup"
  jq -e '.body.user.platform_level == 9 and (.body.user.organizations | length >= 1)' \
    "$EDIR/02-setup.json" >/dev/null || die "setup did not return superadmin + org"
  TOKEN="$(jq -r '.body.access_token' "$EDIR/02-setup.json")"
  local company; company="$(jq -r '.body.user.organizations[0].id' "$EDIR/02-setup.json")"

  http GET /api/auth/me; save 03-me; expect 200 "GET /auth/me"
  jq -e --arg e "$email" '.body.email == $e' "$EDIR/03-me.json" >/dev/null \
    || die "me.email mismatch"

  http POST /api/auth/refresh; save 04-refresh; expect 200 "POST /auth/refresh"
  TOKEN="$(jq -r '.body.access_token' "$EDIR/04-refresh.json")"
  [ "$TOKEN" != "null" ] && [ -n "$TOKEN" ] || die "refresh returned no access_token"

  http GET /api/setup/status; save 05-status-after; expect 200 "setup/status after"
  jq -e '.body.setup_required == false' "$EDIR/05-status-after.json" >/dev/null \
    || die "setup_required still true after claim"

  jq -n --arg token "$TOKEN" --arg company "$company" --arg email "$email" \
    '{access_token:$token, company_id:$company, email:$email}' >"$run/state/auth.json"
  echo "first-run-setup ok — evidence in $EDIR"
}

drive_workspace() {
  local run="$1"; EDIR="$EVIDENCE_DIR/$RUN_ID/session-workspace"
  JAR="$run/state/cookies.txt"
  [ -f "$run/state/auth.json" ] || die "no state/auth.json — run 'drive first-run-setup' first"
  TOKEN="$(jq -r '.access_token' "$run/state/auth.json")"
  local company; company="$(jq -r '.company_id' "$run/state/auth.json")"

  http POST /api/auth/refresh
  [ "$HTTP_CODE" = 200 ] && TOKEN="$(jq -r '.access_token' "$HTTP_BODY")"

  http POST /api/sessions "{\"company_id\":\"$company\"}"
  save 01-create; expect 201 "POST /sessions"
  local sid; sid="$(jq -r '.body.id' "$EDIR/01-create.json")"
  [ "$sid" != "null" ] || die "create returned no session id"

  http GET /api/sessions; save 02-list; expect 200 "GET /sessions"
  jq -e --arg sid "$sid" '.body.sessions | map(.id) | index($sid) != null' \
    "$EDIR/02-list.json" >/dev/null || die "new session missing from list"

  http PATCH "/api/sessions/$sid" '{"title":"verify session","pinned":true}'
  save 03-patch; expect 200 "PATCH /sessions/$sid"
  jq -e '.body.title == "verify session" and .body.pinned == true' \
    "$EDIR/03-patch.json" >/dev/null || die "patch did not apply title/pin"

  http GET "/api/sessions/$sid/messages"; save 04-messages; expect 200 "GET messages"
  jq -e '.body.messages | type == "array"' "$EDIR/04-messages.json" >/dev/null \
    || die "messages response lacks array"

  http DELETE "/api/sessions/$sid"; save 05-delete; expect 204 "DELETE /sessions/$sid"

  http GET /api/sessions; save 06-list-after; expect 200 "GET /sessions after"
  jq -e --arg sid "$sid" '.body.sessions | map(.id) | index($sid) == null' \
    "$EDIR/06-list-after.json" >/dev/null || die "deleted session still listed"
  echo "session-workspace ok — evidence in $EDIR"
}

cmd_drive() {
  local run; run="$(need_run)"; . "$run/run.env"
  HTTP_BODY="$run/state/last-body.json"
  case "${1:-all}" in
    first-run-setup)   drive_setup "$run" ;;
    session-workspace) drive_workspace "$run" ;;
    all)               drive_setup "$run"; drive_workspace "$run" ;;
    *) die "unknown feature '$1' — see features/README.md" ;;
  esac
}

cmd_cleanup() {
  local run; run="$(need_run)"; . "$run/run.env"
  local pid; pid="$(cat "$run/api.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -9 "$pid" 2>/dev/null || true
  fi
  [ "$MODE" = "container" ] && docker stop "$CONTAINER" >/dev/null 2>&1 || true
  if [ "$MODE" = "shared" ]; then
    pg_sql "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE)" || true
  fi
  [ -f "$run/api.log" ] && cp "$run/api.log" "$EVIDENCE_DIR/$RUN_ID/api.log"
  rm -rf "$run"
  [ -d "$EVIDENCE_DIR/$RUN_ID" ] \
    && echo "cleaned run $RUN_ID — evidence kept at $EVIDENCE_DIR/$RUN_ID" \
    || die "cleanup ate the evidence — $EVIDENCE_DIR/$RUN_ID is gone"
}

case "${1:-}" in
  launch)  cmd_launch ;;
  doctor)  cmd_doctor ;;
  drive)   cmd_drive "${2:-all}" ;;
  cleanup) cmd_cleanup ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
