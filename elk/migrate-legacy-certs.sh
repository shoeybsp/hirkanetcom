#!/usr/bin/env bash
set -euo pipefail

LEGACY_DIR="${LEGACY_DIR:-/legacy-certs}"
CA_PRIVATE_DIR="${CA_PRIVATE_DIR:-/certs/ca-private}"
CA_PUBLIC_DIR="${CA_PUBLIC_DIR:-/certs/ca-public}"
ELASTICSEARCH_CERTS_DIR="${ELASTICSEARCH_CERTS_DIR:-/certs/elasticsearch}"
KIBANA_CERTS_DIR="${KIBANA_CERTS_DIR:-/certs/kibana}"
LOGSTASH_CERTS_DIR="${LOGSTASH_CERTS_DIR:-/certs/logstash}"

mkdir -p \
  "${CA_PRIVATE_DIR}" \
  "${CA_PUBLIC_DIR}" \
  "${ELASTICSEARCH_CERTS_DIR}" \
  "${KIBANA_CERTS_DIR}" \
  "${LOGSTASH_CERTS_DIR}"

new_ca_crt="${CA_PRIVATE_DIR}/ca.crt"
new_ca_key="${CA_PRIVATE_DIR}/ca.key"
legacy_ca_crt="${LEGACY_DIR}/ca/ca.crt"
legacy_ca_key="${LEGACY_DIR}/ca/ca.key"

if [[ -s "${new_ca_crt}" || -s "${new_ca_key}" ]]; then
  echo "Split certificate volumes are already initialized; legacy migration is not required."
  exit 0
fi

legacy_crt_exists=0
legacy_key_exists=0
[[ -s "${legacy_ca_crt}" ]] && legacy_crt_exists=1
[[ -s "${legacy_ca_key}" ]] && legacy_key_exists=1

if (( legacy_crt_exists != legacy_key_exists )); then
  echo "ERROR: Legacy Elastic CA material is incomplete." >&2
  echo "Refusing to migrate or replace the trust root automatically." >&2
  exit 1
fi

if (( legacy_crt_exists == 0 )); then
  echo "No legacy Elastic certificate material was found; first-time bootstrap will create it."
  exit 0
fi

echo "Migrating the existing Elastic trust root into split certificate volumes."
install -o 0 -g 0 -m 0644 "${legacy_ca_crt}" "${new_ca_crt}"
install -o 0 -g 0 -m 0600 "${legacy_ca_key}" "${new_ca_key}"
install -o 1000 -g 0 -m 0644 "${legacy_ca_crt}" "${CA_PUBLIC_DIR}/ca.crt"

copy_service_pair() {
  local service="$1"
  local destination="$2"
  local legacy_crt="${LEGACY_DIR}/${service}/${service}.crt"
  local legacy_key="${LEGACY_DIR}/${service}/${service}.key"

  if [[ -s "${legacy_crt}" && -s "${legacy_key}" ]]; then
    install -o 1000 -g 0 -m 0644 "${legacy_crt}" "${destination}/${service}.crt"
    install -o 1000 -g 0 -m 0640 "${legacy_key}" "${destination}/${service}.key"
    echo "Migrated ${service} certificate pair."
  elif [[ -s "${legacy_crt}" || -s "${legacy_key}" ]]; then
    echo "Legacy ${service} certificate pair is incomplete; it will be reissued from the migrated CA."
  fi
}

copy_service_pair elasticsearch "${ELASTICSEARCH_CERTS_DIR}"
copy_service_pair kibana "${KIBANA_CERTS_DIR}"
copy_service_pair logstash "${LOGSTASH_CERTS_DIR}"

if [[ -s "${LEGACY_DIR}/logstash/logstash.pkcs8.key" ]]; then
  install -o 1000 -g 0 -m 0640 \
    "${LEGACY_DIR}/logstash/logstash.pkcs8.key" \
    "${LOGSTASH_CERTS_DIR}/logstash.pkcs8.key"
fi

echo "Legacy Elastic certificate migration completed without changing the CA."
