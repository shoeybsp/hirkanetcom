#!/usr/bin/env bash
set -euo pipefail

CERTUTIL="${CERTUTIL:-/usr/share/elasticsearch/bin/elasticsearch-certutil}"
CA_PRIVATE_DIR="${CA_PRIVATE_DIR:-/certs/ca-private}"
CA_PUBLIC_DIR="${CA_PUBLIC_DIR:-/certs/ca-public}"
ELASTICSEARCH_CERTS_DIR="${ELASTICSEARCH_CERTS_DIR:-/certs/elasticsearch}"
KIBANA_CERTS_DIR="${KIBANA_CERTS_DIR:-/certs/kibana}"
LOGSTASH_CERTS_DIR="${LOGSTASH_CERTS_DIR:-/certs/logstash}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p \
  "${CA_PRIVATE_DIR}" \
  "${CA_PUBLIC_DIR}" \
  "${ELASTICSEARCH_CERTS_DIR}" \
  "${KIBANA_CERTS_DIR}" \
  "${LOGSTASH_CERTS_DIR}"

ca_crt="${CA_PRIVATE_DIR}/ca.crt"
ca_key="${CA_PRIVATE_DIR}/ca.key"
ca_crt_exists=0
ca_key_exists=0
[[ -s "${ca_crt}" ]] && ca_crt_exists=1
[[ -s "${ca_key}" ]] && ca_key_exists=1

if (( ca_crt_exists != ca_key_exists )); then
  echo "ERROR: Elastic CA material is incomplete." >&2
  echo "Refusing to replace the trust root automatically." >&2
  echo "Restore the missing CA file or run the explicit CA rotation procedure." >&2
  exit 1
fi

if (( ca_crt_exists == 0 )); then
  echo "No Elastic CA exists; creating the initial trust root."
  "${CERTUTIL}" ca \
    --silent \
    --pem \
    --out "${TMP_DIR}/ca.zip"
  test -s "${TMP_DIR}/ca.zip"
  unzip -oq "${TMP_DIR}/ca.zip" -d "${TMP_DIR}/generated-ca"
  install -o 0 -g 0 -m 0644 "${TMP_DIR}/generated-ca/ca/ca.crt" "${ca_crt}"
  install -o 0 -g 0 -m 0600 "${TMP_DIR}/generated-ca/ca/ca.key" "${ca_key}"
else
  echo "Reusing the existing Elastic trust root."
fi

install -o 1000 -g 0 -m 0644 "${ca_crt}" "${CA_PUBLIC_DIR}/ca.crt"
rm -f "${CA_PUBLIC_DIR}/ca.key"

cat > "${TMP_DIR}/instances.yml" <<'EOF_INSTANCES'
instances:
  - name: elasticsearch
    dns: [elasticsearch, localhost]
    ip: [127.0.0.1]
  - name: kibana
    dns: [kibana, localhost]
    ip: [127.0.0.1]
  - name: logstash
    dns: [logstash, localhost]
    ip: [127.0.0.1]
EOF_INSTANCES

service_pair_complete() {
  local service="$1"
  local directory="$2"
  [[ -s "${directory}/${service}.crt" && -s "${directory}/${service}.key" ]]
}

if ! service_pair_complete elasticsearch "${ELASTICSEARCH_CERTS_DIR}" || \
   ! service_pair_complete kibana "${KIBANA_CERTS_DIR}" || \
   ! service_pair_complete logstash "${LOGSTASH_CERTS_DIR}"; then
  echo "One or more service certificates are missing; reissuing them with the existing CA."

  rm -f \
    "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.crt" \
    "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.key" \
    "${KIBANA_CERTS_DIR}/kibana.crt" \
    "${KIBANA_CERTS_DIR}/kibana.key" \
    "${LOGSTASH_CERTS_DIR}/logstash.crt" \
    "${LOGSTASH_CERTS_DIR}/logstash.key" \
    "${LOGSTASH_CERTS_DIR}/logstash.pkcs8.key"

  "${CERTUTIL}" cert \
    --silent \
    --pem \
    --in "${TMP_DIR}/instances.yml" \
    --out "${TMP_DIR}/certs.zip" \
    --ca-cert "${ca_crt}" \
    --ca-key "${ca_key}"

  test -s "${TMP_DIR}/certs.zip"
  unzip -oq "${TMP_DIR}/certs.zip" -d "${TMP_DIR}/generated-certs"

  install -o 1000 -g 0 -m 0644 \
    "${TMP_DIR}/generated-certs/elasticsearch/elasticsearch.crt" \
    "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.crt"
  install -o 1000 -g 0 -m 0640 \
    "${TMP_DIR}/generated-certs/elasticsearch/elasticsearch.key" \
    "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.key"

  install -o 1000 -g 0 -m 0644 \
    "${TMP_DIR}/generated-certs/kibana/kibana.crt" \
    "${KIBANA_CERTS_DIR}/kibana.crt"
  install -o 1000 -g 0 -m 0640 \
    "${TMP_DIR}/generated-certs/kibana/kibana.key" \
    "${KIBANA_CERTS_DIR}/kibana.key"

  install -o 1000 -g 0 -m 0644 \
    "${TMP_DIR}/generated-certs/logstash/logstash.crt" \
    "${LOGSTASH_CERTS_DIR}/logstash.crt"
  install -o 1000 -g 0 -m 0640 \
    "${TMP_DIR}/generated-certs/logstash/logstash.key" \
    "${LOGSTASH_CERTS_DIR}/logstash.key"
fi

for required_file in \
  "${ca_crt}" \
  "${ca_key}" \
  "${CA_PUBLIC_DIR}/ca.crt" \
  "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.crt" \
  "${ELASTICSEARCH_CERTS_DIR}/elasticsearch.key" \
  "${KIBANA_CERTS_DIR}/kibana.crt" \
  "${KIBANA_CERTS_DIR}/kibana.key" \
  "${LOGSTASH_CERTS_DIR}/logstash.crt" \
  "${LOGSTASH_CERTS_DIR}/logstash.key"; do
  test -s "${required_file}"
done

chmod 0700 "${CA_PRIVATE_DIR}"
chmod 0600 "${ca_key}"
chmod 0644 "${ca_crt}" "${CA_PUBLIC_DIR}/ca.crt"
find "${ELASTICSEARCH_CERTS_DIR}" "${KIBANA_CERTS_DIR}" "${LOGSTASH_CERTS_DIR}" \
  -type d -exec chmod 0750 {} +
find "${ELASTICSEARCH_CERTS_DIR}" "${KIBANA_CERTS_DIR}" "${LOGSTASH_CERTS_DIR}" \
  -type f -name '*.crt' -exec chmod 0644 {} +
find "${ELASTICSEARCH_CERTS_DIR}" "${KIBANA_CERTS_DIR}" "${LOGSTASH_CERTS_DIR}" \
  -type f -name '*.key' -exec chmod 0640 {} +
chown -R 1000:0 \
  "${CA_PUBLIC_DIR}" \
  "${ELASTICSEARCH_CERTS_DIR}" \
  "${KIBANA_CERTS_DIR}" \
  "${LOGSTASH_CERTS_DIR}"

echo "Elastic TLS certificates are ready."
