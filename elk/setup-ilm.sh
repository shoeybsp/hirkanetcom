#!/usr/bin/env sh
set -eu
curl --fail --cacert /certs/ca/ca.crt -u elastic:${ELASTIC_PASSWORD} -X PUT https://localhost:9200/_ilm/policy/hirkanet-logs-policy -H 'Content-Type: application/json' -d '{"policy":{"phases":{"hot":{"actions":{"rollover":{"max_primary_shard_size":"10gb","max_age":"1d"}}},"delete":{"min_age":"30d","actions":{"delete":{}}}}}}'
