#!/usr/bin/env bash
set -euo pipefail

if [ -n "${ELASTIC_PASSWORD_FILE:-}" ]; then
  ELASTIC_PASSWORD="$(cat "${ELASTIC_PASSWORD_FILE}")"
fi
: "${ELASTIC_PASSWORD:?ELASTIC_PASSWORD or ELASTIC_PASSWORD_FILE is required}"
ELASTICSEARCH_URL="${ELASTICSEARCH_URL:-https://elasticsearch:9200}"
ELASTICSEARCH_CA="${ELASTICSEARCH_CA:-/usr/share/elasticsearch/config/certs/ca/ca.crt}"

curl_es() {
  curl --fail --silent --show-error \
    --cacert "${ELASTICSEARCH_CA}" \
    --user "elastic:${ELASTIC_PASSWORD}" "$@"
}

curl_es -X PUT "${ELASTICSEARCH_URL}/_ilm/policy/hirkanet-logs-policy" \
  -H 'Content-Type: application/json' \
  -d '{
    "policy": {
      "phases": {
        "hot": {
          "actions": {
            "rollover": {
              "max_primary_shard_size": "10gb",
              "max_age": "1d"
            }
          }
        },
        "delete": {
          "min_age": "30d",
          "actions": {"delete": {}}
        }
      }
    }
  }'

curl_es -X PUT "${ELASTICSEARCH_URL}/_index_template/hirkanet-logs-template" \
  -H 'Content-Type: application/json' \
  -d '{
    "index_patterns": ["hirkanet-logs-*"],
    "priority": 200,
    "template": {
      "settings": {
        "index.lifecycle.name": "hirkanet-logs-policy",
        "index.lifecycle.rollover_alias": "hirkanet-logs"
      }
    }
  }'

status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert "${ELASTICSEARCH_CA}" --user "elastic:${ELASTIC_PASSWORD}" \
  "${ELASTICSEARCH_URL}/hirkanet-logs-000001")
if [ "${status}" = "404" ]; then
  curl_es -X PUT "${ELASTICSEARCH_URL}/hirkanet-logs-000001" \
    -H 'Content-Type: application/json' \
    -d '{"aliases":{"hirkanet-logs":{"is_write_index":true}}}'
fi

curl_es -X PUT "${ELASTICSEARCH_URL}/_ilm/policy/hirkanet-dead-letter-policy" \
  -H 'Content-Type: application/json' \
  -d '{
    "policy": {
      "phases": {
        "hot": {
          "actions": {
            "rollover": {
              "max_primary_shard_size": "5gb",
              "max_age": "7d"
            }
          }
        },
        "delete": {
          "min_age": "30d",
          "actions": {"delete": {}}
        }
      }
    }
  }'

curl_es -X PUT "${ELASTICSEARCH_URL}/_index_template/hirkanet-dead-letter-template" \
  -H 'Content-Type: application/json' \
  -d '{
    "index_patterns": ["hirkanet-dead-letter-*"],
    "priority": 210,
    "template": {
      "settings": {
        "index.lifecycle.name": "hirkanet-dead-letter-policy",
        "index.lifecycle.rollover_alias": "hirkanet-dead-letter"
      }
    }
  }'

dead_letter_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert "${ELASTICSEARCH_CA}" --user "elastic:${ELASTIC_PASSWORD}" \
  "${ELASTICSEARCH_URL}/hirkanet-dead-letter-000001")
if [ "${dead_letter_status}" = "404" ]; then
  curl_es -X PUT "${ELASTICSEARCH_URL}/hirkanet-dead-letter-000001" \
    -H 'Content-Type: application/json' \
    -d '{"aliases":{"hirkanet-dead-letter":{"is_write_index":true}}}'
fi

echo "Hirkanet normal-log and dead-letter ILM policies, templates, and rollover aliases are configured."
