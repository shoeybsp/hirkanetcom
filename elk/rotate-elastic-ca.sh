#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm-trust-root-rotation" ]]; then
  cat >&2 <<'USAGE'
Refusing to rotate the Elastic trust root without explicit confirmation.

Usage:
  ./elk/rotate-elastic-ca.sh --confirm-trust-root-rotation

This operation removes only Elastic certificate volumes. Elasticsearch, Kibana,
Logstash, and Filebeat data volumes are preserved. Every previously exported
CA certificate becomes invalid and must be redistributed.
USAGE
  exit 2
fi

compose=(docker compose -f docker-compose.elastic.yml)
config_file="$(mktemp)"
trap 'rm -f "${config_file}"' EXIT
"${compose[@]}" config --format json > "${config_file}"

volume_name_for() {
  local logical_name="$1"
  python3 - "${config_file}" "${logical_name}" <<'PY'
import json
import sys

config_path, logical_name = sys.argv[1:]
with open(config_path, encoding="utf-8") as handle:
    config = json.load(handle)
project_name = config.get("name", "hirkanet-observability")
volume = config.get("volumes", {}).get(logical_name, {}) or {}
print(volume.get("name") or f"{project_name}_{logical_name}")
PY
}

legacy_volume="$(volume_name_for legacy_elastic_certs)"
public_ca_volume="$(volume_name_for elastic_ca_public)"
certificate_volumes=(
  "${legacy_volume}"
  "$(volume_name_for elastic_ca_private)"
  "${public_ca_volume}"
  "$(volume_name_for elasticsearch_certs)"
  "$(volume_name_for kibana_certs)"
  "$(volume_name_for logstash_certs)"
)

backup_dir="elastic-ca-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${backup_dir}"

backup_public_ca() {
  local volume_name="$1"
  local candidate_path="$2"

  if ! docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    return 1
  fi

  docker run --rm \
    -v "${volume_name}:/certs:ro" \
    -v "${PWD}/${backup_dir}:/backup" \
    alpine:3.21.3 \
    sh -ec "
      if [ -s '${candidate_path}' ]; then
        cp '${candidate_path}' /backup/old-ca.crt
        sha256sum '${candidate_path}' > /backup/old-ca.sha256
      else
        exit 1
      fi
    "
}

backup_public_ca "${public_ca_volume}" /certs/ca.crt \
  || backup_public_ca "${legacy_volume}" /certs/ca/ca.crt \
  || echo "No previous public CA was available to back up."

echo "Removing Elastic containers while preserving all data volumes..."
"${compose[@]}" down --remove-orphans

echo "Removing certificate volumes only..."
for volume_name in "${certificate_volumes[@]}"; do
  if docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    docker volume rm "${volume_name}"
  fi
done

echo "Creating a new CA and service certificates..."
"${compose[@]}" up -d --build

container_id=""
for _ in $(seq 1 120); do
  container_id="$("${compose[@]}" ps -q elasticsearch 2>/dev/null || true)"
  if [[ -n "${container_id}" ]]; then
    health_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || true)"
    if [[ "${health_status}" == "healthy" ]]; then
      break
    fi
    if [[ "${health_status}" == "unhealthy" || "${health_status}" == "exited" ]]; then
      echo "ERROR: Elasticsearch failed during trust-root rotation." >&2
      "${compose[@]}" logs --tail=200 elastic-certs-migrate elastic-certs-setup openssl-helper elasticsearch >&2 || true
      exit 1
    fi
  fi
  sleep 2
done

if [[ -z "${container_id}" ]]; then
  echo "ERROR: Elasticsearch container was not created." >&2
  exit 1
fi

final_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
if [[ "${final_health}" != "healthy" ]]; then
  echo "ERROR: Elasticsearch did not become healthy after CA rotation." >&2
  "${compose[@]}" logs --tail=200 elastic-certs-migrate elastic-certs-setup openssl-helper elasticsearch >&2 || true
  exit 1
fi

mkdir -p "${backup_dir}/new"
"${compose[@]}" cp \
  elasticsearch:/usr/share/elasticsearch/config/certs/ca/ca.crt \
  "${backup_dir}/new/hirkanet-elastic-ca.crt"
sha256sum "${backup_dir}/new/hirkanet-elastic-ca.crt" \
  > "${backup_dir}/new/hirkanet-elastic-ca.sha256"

cat <<MSG
Elastic trust-root rotation completed.

Old CA evidence when available: ${backup_dir}/
New CA certificate: ${backup_dir}/new/hirkanet-elastic-ca.crt

Required follow-up:
1. Redistribute and trust the new CA on every browser, CLI client, monitoring agent, and integration.
2. Verify Elasticsearch, Kibana, Logstash, and Filebeat health.
3. Run ./elk/verify-ingestion.sh.
4. Remove the old CA from trust stores only after migration is complete.
5. Record the rotation date and new SHA-256 fingerprint in change management.
MSG
