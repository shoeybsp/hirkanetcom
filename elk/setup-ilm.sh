#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${ELASTIC_PASSWORD_FILE:-}" ]]; then
  ELASTIC_PASSWORD="$(cat "${ELASTIC_PASSWORD_FILE}")"
fi
: "${ELASTIC_PASSWORD:?ELASTIC_PASSWORD or ELASTIC_PASSWORD_FILE is required}"

ELASTICSEARCH_URL="${ELASTICSEARCH_URL:-https://elasticsearch:9200}"
ELASTICSEARCH_CA="${ELASTICSEARCH_CA:-/usr/share/elasticsearch/config/certs/ca/ca.crt}"

curl_es() {
  curl --fail --silent --show-error \
    --cacert "${ELASTICSEARCH_CA}" \
    --user "elastic:${ELASTIC_PASSWORD}" \
    "$@"
}

http_status() {
  curl --silent --output /dev/null --write-out '%{http_code}' \
    --cacert "${ELASTICSEARCH_CA}" \
    --user "elastic:${ELASTIC_PASSWORD}" \
    "$1"
}

ensure_write_alias() {
  local alias_name="$1"
  local initial_index="$2"
  local alias_status
  local index_status

  alias_status="$(http_status "${ELASTICSEARCH_URL}/_alias/${alias_name}")"
  if [[ "${alias_status}" == "200" ]]; then
    return 0
  fi
  if [[ "${alias_status}" != "404" ]]; then
    echo "ERROR: unexpected status ${alias_status} while checking alias ${alias_name}" >&2
    exit 1
  fi

  index_status="$(http_status "${ELASTICSEARCH_URL}/${initial_index}")"
  if [[ "${index_status}" == "404" ]]; then
    curl_es -X PUT "${ELASTICSEARCH_URL}/${initial_index}" \
      -H 'Content-Type: application/json' \
      -d "{\"aliases\":{\"${alias_name}\":{\"is_write_index\":true}}}"
  elif [[ "${index_status}" == "200" ]]; then
    curl_es -X POST "${ELASTICSEARCH_URL}/_aliases" \
      -H 'Content-Type: application/json' \
      -d "{\"actions\":[{\"add\":{\"index\":\"${initial_index}\",\"alias\":\"${alias_name}\",\"is_write_index\":true}}]}"
  else
    echo "ERROR: unexpected status ${index_status} while checking ${initial_index}" >&2
    exit 1
  fi
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
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "index.lifecycle.name": "hirkanet-logs-policy",
        "index.lifecycle.rollover_alias": "hirkanet-logs",
        "index.mapping.total_fields.limit": 2000
      },
      "mappings": {
        "dynamic": true,
        "properties": {
          "@timestamp": {"type": "date"},
          "service": {"properties": {"name": {"type": "keyword"}}},
          "event": {
            "properties": {
              "dataset": {"type": "keyword"},
              "duration": {"type": "long"},
              "id": {"type": "keyword"},
              "kind": {"type": "keyword"},
              "type": {"type": "keyword"}
            }
          },
          "log": {"properties": {"level": {"type": "keyword"}}},
          "request": {"properties": {"id": {"type": "keyword"}}},
          "user": {"properties": {"id": {"type": "keyword"}}},
          "http": {
            "properties": {
              "response": {
                "properties": {
                  "status_code": {"type": "integer"}
                }
              }
            }
          },
          "container": {
            "properties": {
              "id": {"type": "keyword"},
              "name": {"type": "keyword"},
              "image": {"properties": {"name": {"type": "keyword"}}}
            }
          }
        }
      }
    }
  }'

ensure_write_alias "hirkanet-logs" "hirkanet-logs-000001"

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
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "index.lifecycle.name": "hirkanet-dead-letter-policy",
        "index.lifecycle.rollover_alias": "hirkanet-dead-letter",
        "index.mapping.total_fields.limit": 1000
      },
      "mappings": {
        "dynamic": true,
        "properties": {
          "@timestamp": {"type": "date"},
          "event": {
            "properties": {
              "dataset": {"type": "keyword"},
              "id": {"type": "keyword"},
              "kind": {"type": "keyword"},
              "original": {"type": "text", "index": true}
            }
          },
          "error": {
            "properties": {
              "type": {"type": "keyword"},
              "message": {"type": "text"}
            }
          },
          "container": {
            "properties": {
              "id": {"type": "keyword"},
              "name": {"type": "keyword"}
            }
          }
        }
      }
    }
  }'

ensure_write_alias "hirkanet-dead-letter" "hirkanet-dead-letter-000001"

echo "Hirkanet normal-log and dead-letter ILM policies, templates, and rollover aliases are configured."
