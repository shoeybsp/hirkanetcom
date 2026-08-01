#!/usr/bin/env sh
set -eu

CERTS_DIR="${LOGSTASH_CERTS_DIR:-/certs/logstash}"
source_key="${CERTS_DIR}/logstash.key"
target_key="${CERTS_DIR}/logstash.pkcs8.key"
temporary_key="${target_key}.tmp"

test -s "${source_key}"

if [ -s "${target_key}" ] && openssl pkey -in "${target_key}" -noout >/dev/null 2>&1; then
  echo "Existing Logstash PKCS#8 key is valid."
  exit 0
fi

rm -f "${temporary_key}"
openssl pkcs8 \
  -inform PEM \
  -in "${source_key}" \
  -topk8 \
  -nocrypt \
  -outform PEM \
  -out "${temporary_key}"

openssl pkey -in "${temporary_key}" -noout >/dev/null
chown 1000:0 "${temporary_key}"
chmod 0640 "${temporary_key}"
mv -f "${temporary_key}" "${target_key}"

echo "Logstash PKCS#8 key is ready."
