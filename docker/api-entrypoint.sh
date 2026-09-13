#!/bin/sh
# Entrypoint for the api image (ADR 0027). Inert unless AUTO_SECRETS=true —
# pro/external-db deploys unset it and provide JWT_SECRET + BYOK_ENCRYPTION_KEY
# themselves. All-in-one compose sets it so `docker compose up` needs no .env:
# the `migrate` service runs first and writes the file, api/scheduler source the
# same persisted values from the shared `appdata` volume.
set -e

if [ "${AUTO_SECRETS:-false}" = "true" ]; then
  f="${AUTO_SECRETS_FILE:-/app/data/.secrets.env}"
  mkdir -p "$(dirname "$f")"
  [ -f "$f" ] && . "$f"
  if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
  fi
  if [ -z "$BYOK_ENCRYPTION_KEY" ]; then
    BYOK_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
  fi
  printf 'JWT_SECRET=%s\nBYOK_ENCRYPTION_KEY=%s\n' "$JWT_SECRET" "$BYOK_ENCRYPTION_KEY" >"$f"
  chmod 600 "$f"
  export JWT_SECRET BYOK_ENCRYPTION_KEY
fi

exec "$@"
