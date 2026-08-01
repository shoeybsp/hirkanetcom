#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
KEEP_MINIMUM="${KEEP_MINIMUM:-7}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

usage() {
  cat <<USAGE
Usage: $0 [--no-restore-test]

Creates a PostgreSQL custom-format backup, checksum and metadata file.
By default, it also performs a disposable restore test before marking the
backup successful.

Environment:
  COMPOSE_FILE    Compose file (default: docker-compose.yml)
  BACKUP_DIR      Destination directory (default: ./backups/postgres)
  RETENTION_DAYS  Delete backups older than this many days (default: 14)
  KEEP_MINIMUM    Always retain at least this many newest backups (default: 7)
USAGE
}

RUN_RESTORE_TEST=1
case "${1:-}" in
  "") ;;
  --no-restore-test) RUN_RESTORE_TEST=0 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

for cmd in docker sha256sum awk sed date find sort; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: required command not found: $cmd" >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

DB_NAME="$(docker compose -f "$COMPOSE_FILE" exec -T db sh -ec 'printf %s "$POSTGRES_DB"')"
DB_USER="$(docker compose -f "$COMPOSE_FILE" exec -T db sh -ec 'printf %s "$POSTGRES_USER"')"
POSTGRES_VERSION="$(docker compose -f "$COMPOSE_FILE" exec -T db postgres --version | tr -d '\r')"

if [[ -z "$DB_NAME" || -z "$DB_USER" ]]; then
  echo "ERROR: POSTGRES_DB or POSTGRES_USER is empty in the database container." >&2
  exit 1
fi

SAFE_DB_NAME="$(printf '%s' "$DB_NAME" | sed 's/[^A-Za-z0-9_.-]/_/g')"
BASE="${SAFE_DB_NAME}-${TIMESTAMP}"
DUMP_PATH="$BACKUP_DIR/${BASE}.dump"
TEMP_PATH="$DUMP_PATH.partial"
CHECKSUM_PATH="$DUMP_PATH.sha256"
META_PATH="$DUMP_PATH.meta"

cleanup() {
  rm -f "$TEMP_PATH"
}
trap cleanup EXIT

echo "Creating PostgreSQL backup: $DUMP_PATH"
docker compose -f "$COMPOSE_FILE" exec -T db sh -ec '
  export PGPASSWORD="$(cat /run/secrets/postgres_password)"
  exec pg_dump \
    --host=127.0.0.1 \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges
' > "$TEMP_PATH"

if [[ ! -s "$TEMP_PATH" ]]; then
  echo "ERROR: pg_dump produced an empty file." >&2
  exit 1
fi

# Validate the archive structure before publishing it.
docker compose -f "$COMPOSE_FILE" exec -T db pg_restore --list < "$TEMP_PATH" >/dev/null

mv "$TEMP_PATH" "$DUMP_PATH"
chmod 600 "$DUMP_PATH"
(
  cd "$BACKUP_DIR"
  sha256sum "$(basename "$DUMP_PATH")" > "$(basename "$CHECKSUM_PATH")"
)
chmod 600 "$CHECKSUM_PATH"

cat > "$META_PATH" <<META
created_at_utc=$TIMESTAMP
database=$DB_NAME
user=$DB_USER
postgres_version=$POSTGRES_VERSION
format=pg_dump_custom
checksum_file=$(basename "$CHECKSUM_PATH")
restore_test=pending
META
chmod 600 "$META_PATH"

if [[ "$RUN_RESTORE_TEST" -eq 1 ]]; then
  "$(dirname "$0")/postgres-restore-test.sh" "$DUMP_PATH"
  sed -i 's/^restore_test=pending$/restore_test=passed/' "$META_PATH"
else
  sed -i 's/^restore_test=pending$/restore_test=skipped/' "$META_PATH"
fi

# Retention: delete expired sets but always keep the newest KEEP_MINIMUM dumps.
mapfile -t ALL_DUMPS < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
if (( ${#ALL_DUMPS[@]} > KEEP_MINIMUM )); then
  for ((i=KEEP_MINIMUM; i<${#ALL_DUMPS[@]}; i++)); do
    candidate="${ALL_DUMPS[$i]}"
    if find "$candidate" -maxdepth 0 -mtime "+$RETENTION_DAYS" -print -quit | grep -q .; then
      rm -f "$candidate" "$candidate.sha256" "$candidate.meta"
    fi
  done
fi

echo "Backup completed and verified: $DUMP_PATH"
