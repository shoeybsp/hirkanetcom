#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DUMP_PATH=""
TARGET_DB=""
CONFIRM=""
ALLOW_PRODUCTION_TARGET=0

usage() {
  cat <<USAGE
Usage: $0 --backup FILE --target-db NAME --confirm-restore [--allow-production-target]

Restores a custom-format backup into an explicitly named database. By default,
restoring over the configured production database is refused.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup) DUMP_PATH="${2:-}"; shift 2 ;;
    --target-db) TARGET_DB="${2:-}"; shift 2 ;;
    --confirm-restore) CONFIRM=1; shift ;;
    --allow-production-target) ALLOW_PRODUCTION_TARGET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n "$DUMP_PATH" && -f "$DUMP_PATH" && -n "$TARGET_DB" && -n "$CONFIRM" ]] || { usage >&2; exit 2; }
[[ "$TARGET_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "ERROR: invalid target database name." >&2; exit 1; }

PRODUCTION_DB="$(docker compose -f "$COMPOSE_FILE" exec -T db sh -ec 'printf %s "$POSTGRES_DB"')"
if [[ "$TARGET_DB" == "$PRODUCTION_DB" && "$ALLOW_PRODUCTION_TARGET" -ne 1 ]]; then
  echo "ERROR: refusing to restore over production database '$PRODUCTION_DB'." >&2
  echo "Use --allow-production-target only during a documented outage after taking a fresh backup." >&2
  exit 1
fi

if [[ -f "$DUMP_PATH.sha256" ]]; then
  (cd "$(dirname "$DUMP_PATH")" && sha256sum --check "$(basename "$DUMP_PATH.sha256")")
fi

docker compose -f "$COMPOSE_FILE" exec -T db pg_restore --list < "$DUMP_PATH" >/dev/null

# The target must not already exist unless production replacement was explicitly authorized.
if [[ "$TARGET_DB" == "$PRODUCTION_DB" ]]; then
  docker compose -f "$COMPOSE_FILE" stop app migrate >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
    export PGPASSWORD="$(cat /run/secrets/postgres_password)"
    psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname=postgres --no-password --set=ON_ERROR_STOP=1 \
      --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$1'\'' AND pid <> pg_backend_pid();"
    dropdb --host=127.0.0.1 --username="$POSTGRES_USER" --if-exists "$1"
    createdb --host=127.0.0.1 --username="$POSTGRES_USER" "$1"
  ' sh "$TARGET_DB"
else
  docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
    export PGPASSWORD="$(cat /run/secrets/postgres_password)"
    if psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname=postgres --no-password --tuples-only --no-align \
      --command="SELECT 1 FROM pg_database WHERE datname='\''$1'\'';" | grep -q 1; then
      echo "ERROR: target database already exists: $1" >&2
      exit 1
    fi
    createdb --host=127.0.0.1 --username="$POSTGRES_USER" "$1"
  ' sh "$TARGET_DB"
fi

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
  export PGPASSWORD="$(cat /run/secrets/postgres_password)"
  exec pg_restore --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$1" --no-owner --no-privileges --exit-on-error
' sh "$TARGET_DB" < "$DUMP_PATH"

echo "Restore completed into database: $TARGET_DB"
if [[ "$TARGET_DB" == "$PRODUCTION_DB" ]]; then
  echo "Run: docker compose up -d migrate app"
fi
