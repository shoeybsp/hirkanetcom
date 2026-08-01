#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f docker-compose.elastic.yml)
secret_file="${SECRETS_DIR:-./secrets}/elastic_password"

if [[ ! -s "${secret_file}" ]]; then
  echo "ERROR: ${secret_file} is missing or empty." >&2
  exit 1
fi

for service in elasticsearch logstash filebeat; do
  if ! "${compose[@]}" ps --status running --services | grep -qx "${service}"; then
    echo "ERROR: ${service} is not running." >&2
    exit 1
  fi
done

token="hirkanet-e2e-$(date -u +%Y%m%dT%H%M%SZ)-${RANDOM}"
valid_container="${token}-valid"
invalid_container="${token}-invalid"

cleanup() {
  docker rm -f "${valid_container}" "${invalid_container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

valid_event=$(printf '{"@timestamp":"%s","message":"Elastic ingestion verification","service":{"name":"hirkanet"},"event":{"dataset":"hirkanet.test","id":"%s"},"log":{"level":"info"}}' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${token}")
invalid_event="not-json-${token}"

docker run --rm -d \
  --name "${valid_container}" \
  --label hirkanet_log_role=application \
  --env SYNTHETIC_EVENT="${valid_event}" \
  alpine:3.21.3 \
  sh -c 'printf "%s\n" "$SYNTHETIC_EVENT"; sleep 20' >/dev/null

docker run --rm -d \
  --name "${invalid_container}" \
  --label hirkanet_log_role=application \
  --env SYNTHETIC_EVENT="${invalid_event}" \
  alpine:3.21.3 \
  sh -c 'printf "%s\n" "$SYNTHETIC_EVENT"; sleep 20' >/dev/null

query_count() {
  local index_pattern="$1"
  local query_json="$2"
  local password
  password="$(cat "${secret_file}")"
  "${compose[@]}" exec -T elasticsearch \
    curl --fail --silent --show-error \
      --cacert config/certs/ca/ca.crt \
      --user "elastic:${password}" \
      --header 'Content-Type: application/json' \
      --request GET \
      "https://127.0.0.1:9200/${index_pattern}/_count" \
      --data "${query_json}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])'
}

valid_query=$(printf '{"query":{"term":{"event.id":"%s"}}}' "${token}")
invalid_query=$(printf '{"query":{"match_phrase":{"event.original":"%s"}}}' "${token}")

valid_normal=0
valid_dead=0
invalid_normal=0
invalid_dead=0

for _ in $(seq 1 30); do
  valid_normal="$(query_count 'hirkanet-logs-*' "${valid_query}" || echo 0)"
  valid_dead="$(query_count 'hirkanet-dead-letter-*' "${valid_query}" || echo 0)"
  invalid_normal="$(query_count 'hirkanet-logs-*' "${invalid_query}" || echo 0)"
  invalid_dead="$(query_count 'hirkanet-dead-letter-*' "${invalid_query}" || echo 0)"

  if (( valid_normal >= 1 && invalid_dead >= 1 )); then
    break
  fi
  sleep 2
done

if (( valid_normal < 1 )); then
  echo "ERROR: valid application JSON did not reach hirkanet-logs." >&2
  exit 1
fi
if (( valid_dead != 0 )); then
  echo "ERROR: valid application JSON was duplicated into dead-letter indices." >&2
  exit 1
fi
if (( invalid_normal != 0 )); then
  echo "ERROR: malformed application JSON was written to normal indices." >&2
  exit 1
fi
if (( invalid_dead < 1 )); then
  echo "ERROR: malformed application JSON did not reach dead-letter indices." >&2
  exit 1
fi

printf 'Elastic ingestion verification passed. token=%s normal=%s dead_letter=%s\n' \
  "${token}" "${valid_normal}" "${invalid_dead}"
