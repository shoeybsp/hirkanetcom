#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DUMP_PATH="${1:-}"

if [[ -z "$DUMP_PATH" || ! -f "$DUMP_PATH" ]]; then
  echo "Usage: $0 /path/to/backup.dump" >&2
  exit 2
fi

CHECKSUM_PATH="$DUMP_PATH.sha256"
if [[ -f "$CHECKSUM_PATH" ]]; then
  (cd "$(dirname "$DUMP_PATH")" && sha256sum --check "$(basename "$CHECKSUM_PATH")")
else
  echo "WARNING: checksum file not found: $CHECKSUM_PATH" >&2
fi

TEST_DB="hirkanet_restore_test_$(date -u +%Y%m%d%H%M%S)_$$"

cleanup() {
  docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
    export PGPASSWORD="$(cat /run/secrets/postgres_password)"
    psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname=postgres --no-password \
      --set=ON_ERROR_STOP=1 --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$1'\'' AND pid <> pg_backend_pid();" >/dev/null
    dropdb --host=127.0.0.1 --username="$POSTGRES_USER" --if-exists "$1"
  ' sh "$TEST_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Testing restore into disposable database: $TEST_DB"
docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
  export PGPASSWORD="$(cat /run/secrets/postgres_password)"
  createdb --host=127.0.0.1 --username="$POSTGRES_USER" "$1"
' sh "$TEST_DB"

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
  export PGPASSWORD="$(cat /run/secrets/postgres_password)"
  exec pg_restore \
    --host=127.0.0.1 \
    --username="$POSTGRES_USER" \
    --dbname="$1" \
    --no-owner \
    --no-privileges \
    --exit-on-error
' sh "$TEST_DB" < "$DUMP_PATH"

# Verify that the expected application and migration tables exist.
docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
  export PGPASSWORD="$(cat /run/secrets/postgres_password)"
  count=$(psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$1" --no-password --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command="SELECT count(*) FROM information_schema.tables WHERE table_schema='\''public'\'' AND table_name IN ('\''users'\'', '\''services'\'', '\''subscriptions'\'', '\''blog_categories'\'', '\''blog_posts'\'', '\''alembic_version'\'');")
  [ "$count" -eq 6 ] || { echo "ERROR: expected schema tables are missing after restore (found $count/6)." >&2; exit 1; }
  psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$1" --no-password --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command="SELECT version_num FROM alembic_version;" >/dev/null
' sh "$TEST_DB"

echo "Restore test passed: $DUMP_PATH"
