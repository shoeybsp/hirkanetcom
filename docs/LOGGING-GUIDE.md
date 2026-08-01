# Hirkanet Logging Guide

## Data flow

```text
Hirkanet application container ─┐
                                ├─ Docker JSON logs
PostgreSQL container ───────────┘
          |
          v
Filebeat filestream
  + restricted Docker metadata proxy
          |
          | TLS with full hostname verification
          v
Logstash
  + application JSON parsing
  + PostgreSQL classification
  + conditional dead-letter routing
          |
          | HTTPS with full hostname verification
          v
Elasticsearch ILM aliases
  ├─ hirkanet-logs
  └─ hirkanet-dead-letter
          |
          v
Kibana
```

Filebeat selects containers using stable Compose labels:

```text
hirkanet_log_role=application
hirkanet_log_role=database
```

Container names are not used because Compose-generated names may change.

## Application events

The Flask application emits one JSON object per log line. A typical event is:

```json
{
  "@timestamp": "2026-08-01T10:00:00+00:00",
  "message": "HTTP request completed",
  "log": {
    "level": "info",
    "logger": "hirkanet.http"
  },
  "service": {
    "name": "hirkanet"
  },
  "event": {
    "dataset": "hirkanet.http_access"
  },
  "request": {
    "id": "b67f74b3-7bb4-42f3-a3ae-9879b57fb5d1"
  },
  "event_type": "access",
  "event_duration": 13800000,
  "http_status_code": 200,
  "user_id": "17"
}
```

Logstash parses valid application JSON into searchable top-level fields and
preserves the original line in:

```text
event.original
```

Compatibility copies are created for commonly used ECS-style fields:

| Application field | Searchable normalized field |
|---|---|
| `event_type` | `event.type` |
| `event_duration` | `event.duration` |
| `http_status_code` | `http.response.status_code` |
| `user_id` | `user.id` |

The original application fields are retained to avoid breaking existing saved
queries during migration.

## PostgreSQL events

PostgreSQL container output is not forced through a JSON parser. Logstash adds:

```text
service.name = postgresql
event.dataset = postgresql.log
event.kind = event
event.original = <original database line>
```

PostgreSQL events are written to the normal `hirkanet-logs` alias.

## Dead-letter behavior

Only malformed application JSON is routed to the dead-letter alias.

A parse-failure event includes:

```text
event.dataset = hirkanet.dead_letter
event.kind = pipeline_error
error.type = json_parse_failure
error.message = Application container log line was not valid JSON
event.original = <unparsed line>
```

Valid events are never written to the dead-letter alias, and malformed
application events are never written to the normal alias.

This is an Elasticsearch dead-letter index path, not Logstash's filesystem DLQ.

## ILM destinations

Logstash uses explicit ILM settings:

```text
Normal alias:       hirkanet-logs
Normal policy:      hirkanet-logs-policy
Dead-letter alias:  hirkanet-dead-letter
Dead-letter policy: hirkanet-dead-letter-policy
```

Do not replace these aliases with date-based index names such as
`hirkanet-logs-%{+YYYY.MM.dd}`. Direct date-based writes bypass the configured
rollover aliases.

## Recommended Kibana data views

Normal logs:

```text
hirkanet-logs*
```

Dead-letter events:

```text
hirkanet-dead-letter*
```

Time field:

```text
@timestamp
```

## Useful Kibana queries

Application access events:

```text
event.dataset : "hirkanet.http_access"
```

HTTP errors:

```text
http.response.status_code >= 500
```

Policy-evaluation events:

```text
event.type : "policy_evaluation_*" or event_type : "policy_evaluation_*"
```

Database logs:

```text
event.dataset : "postgresql.log"
```

Dead-letter events:

```text
event.dataset : "hirkanet.dead_letter"
```

A request by correlation ID:

```text
request.id : "b67f74b3-7bb4-42f3-a3ae-9879b57fb5d1"
```

## Runtime verification

Check service health:

```bash
docker compose -f docker-compose.elastic.yml ps -a
```

Run the complete normal/dead-letter test:

```bash
./elk/verify-ingestion.sh
```

Inspect Logstash pipeline state:

```bash
curl --silent http://127.0.0.1:9600/_node/pipelines
```

The Logstash API is bound inside the container only, so use:

```bash
docker compose -f docker-compose.elastic.yml exec logstash \
  curl --silent http://127.0.0.1:9600/_node/pipelines?pretty
```

Inspect Filebeat output connectivity:

```bash
docker compose -f docker-compose.elastic.yml exec filebeat \
  filebeat test output -e --strict.perms=false
```

## Failure investigation

### No events appear

1. Confirm the application or database container has the expected label.
2. Confirm `docker-socket-proxy` is healthy.
3. Confirm Filebeat is healthy and can reach Logstash.
4. Confirm Logstash's `main` pipeline is loaded.
5. Confirm the `hirkanet-logs` alias has a write index.

### All application events reach dead-letter

The application is probably emitting plaintext instead of JSON. Confirm:

```dotenv
LOG_FORMAT=json
```

Then inspect raw Docker output:

```bash
docker logs --tail=20 <application-container>
```

### Valid events appear in both destinations

That indicates an old Logstash pipeline is still mounted or running. The current
pipeline has mutually exclusive conditional outputs. Recreate Logstash:

```bash
docker compose -f docker-compose.elastic.yml up -d --force-recreate logstash
```

### ILM does not roll over

Verify Logstash is writing to aliases, not direct date-based indices:

```bash
curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  'https://127.0.0.1:9200/_alias/hirkanet-logs?pretty'
```
