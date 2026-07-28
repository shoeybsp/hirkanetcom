# Secure Elastic Stack Setup

## Prerequisites

- Docker Engine and Docker Compose v2
- Linux: `sudo sysctl -w vm.max_map_count=262144`
- At least 4 GB free RAM for the complete stack

## Configuration

```bash
cp .env.example .env
```

Replace all placeholder values. Generate secrets, for example:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

`BOOTSTRAP_ADMIN_PASSWORD` must contain at least 12 characters. Remove both bootstrap admin variables after the initial account has been created.

## Start

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
docker compose logs --tail=100 app filebeat logstash elasticsearch kibana
```

## Install retention policy

```bash
docker compose exec elasticsearch sh -c \
  'curl --fail --cacert config/certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD \
  -X PUT https://localhost:9200/_ilm/policy/hirkanet-logs-policy \
  -H "Content-Type: application/json" \
  -d '\''{"policy":{"phases":{"hot":{"actions":{"rollover":{"max_primary_shard_size":"10gb","max_age":"1d"}}},"delete":{"min_age":"30d","actions":{"delete":{}}}}}}'\'''
```

## Kibana

Open `http://127.0.0.1:5601`, sign in as `elastic`, and use `ELASTIC_PASSWORD`. Create a data view for `hirkanet-logs*` with `@timestamp` as its time field.

## Pipeline

1. Flask and Gunicorn write JSON lines to stdout.
2. Docker rotates and stores the container logs.
3. Filebeat uses a version-9-compatible `filestream` input and keeps only `fortigate-app` and `fortigate-db`.
4. Logstash parses app JSON. Invalid JSON is sent to `hirkanet-dead-letter-*`.
5. Logstash connects to Elasticsearch through TLS.
6. Elasticsearch applies the `hirkanet-logs-policy` lifecycle policy.

## Troubleshooting

```bash
docker compose logs app
docker compose logs filebeat
docker compose logs logstash
curl --cacert <exported-ca.crt> -u elastic https://127.0.0.1:9200/_cluster/health?pretty
```

A missing `hirkanet-logs` index usually means no application traffic, Filebeat cannot read Docker logs, Logstash cannot authenticate, or the ILM policy has not been installed.
