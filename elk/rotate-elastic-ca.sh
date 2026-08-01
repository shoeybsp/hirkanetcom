#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm-trust-root-rotation" ]]; then
  cat >&2 <<'USAGE'
Refusing to rotate the Elastic trust root without explicit confirmation.

Usage:
  ./elk/rotate-elastic-ca.sh --confirm-trust-root-rotation

This operation stops the Elastic services, removes the existing elastic_certs
volume, creates a new private CA and service certificates, and invalidates every
previously exported CA certificate. Redistribute the new CA to all clients.
USAGE
  exit 2
fi

compose=(docker compose -f docker-compose.elastic.yml)

project_name="$("${compose[@]}" config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("name", ""))' || true)"
if [[ -z "$project_name" ]]; then
  project_name="$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
fi
volume_name="${project_name}_elastic_certs"
backup_dir="elastic-ca-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

if docker volume inspect "$volume_name" >/dev/null 2>&1; then
  docker run --rm -v "$volume_name":/certs:ro -v "$PWD/$backup_dir":/backup alpine:3.21 sh -c '
    set -eu
    if [ -f /certs/ca/ca.crt ]; then
      cp /certs/ca/ca.crt /backup/old-ca.crt
      sha256sum /certs/ca/ca.crt > /backup/old-ca.sha256
    fi
  '
fi

echo "Stopping Elastic services..."
"${compose[@]}" stop filebeat kibana logstash elastic-init elasticsearch elastic-certs-setup 2>/dev/null || true

echo "Removing trust-root volume: $volume_name"
docker volume rm "$volume_name"

echo "Creating a new CA and service certificates..."
"${compose[@]}" up -d elastic-certs-setup elasticsearch elastic-init logstash kibana filebeat

mkdir -p "$backup_dir/new"
"${compose[@]}" cp elasticsearch:/usr/share/elasticsearch/config/certs/ca/ca.crt "$backup_dir/new/hirkanet-elastic-ca.crt"
sha256sum "$backup_dir/new/hirkanet-elastic-ca.crt" > "$backup_dir/new/hirkanet-elastic-ca.sha256"

cat <<MSG
Elastic trust-root rotation completed.

Old CA evidence (when available): $backup_dir/
New CA certificate: $backup_dir/new/hirkanet-elastic-ca.crt

Required follow-up:
1. Redistribute and trust the new CA on every browser, CLI client, monitoring agent, and integration.
2. Remove the old CA from trust stores after migration.
3. Verify Elasticsearch, Kibana, Logstash, and Filebeat health.
4. Record the rotation date and new SHA-256 fingerprint in change management.
MSG
