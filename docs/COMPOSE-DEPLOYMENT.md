# Split Docker Compose deployment

Hirkanet uses two independent Compose projects. They do not share a Docker
network.

## 1. Application stack

File:

```text
docker-compose.yml
```

Services:

- `db`
- `migrate`
- `app`

Start:

```bash
docker compose up -d --build
```

Inspect:

```bash
docker compose ps
docker compose logs --tail=100 db migrate app
```

Stop without deleting data:

```bash
docker compose down
```

## 2. Observability stack

File:

```text
docker-compose.elastic.yml
```

One-shot bootstrap services:

- `elastic-certs-migrate`
- `elastic-certs-setup`
- `openssl-helper`
- `elastic-init`

Runtime services:

- `elasticsearch`
- `logstash`
- `kibana`
- `docker-socket-proxy`
- `filebeat`

Start:

```bash
docker compose -f docker-compose.elastic.yml up -d --build
```

Inspect all services, including completed jobs:

```bash
docker compose -f docker-compose.elastic.yml ps -a
docker compose -f docker-compose.elastic.yml logs --tail=100
```

Stop without deleting data:

```bash
docker compose -f docker-compose.elastic.yml down
```

## Network separation

Application networks:

- `app-db`: internal database network
- `frontend`: application/reverse-proxy access network

Observability networks:

- `logging-ingest`: internal Filebeat-to-Logstash network
- `elastic-backend`: internal Logstash/Kibana/init-to-Elasticsearch network
- `docker-metadata`: internal Filebeat-to-Docker-socket-proxy network
- `elastic-access`: non-internal host-access network used only by Elasticsearch
  and Kibana

Published ports remain loopback-only:

```text
127.0.0.1:9200 -> Elasticsearch
127.0.0.1:5601 -> Kibana
```

The two Compose projects do not share a Docker network. Filebeat reads Docker
JSON log files from the host and uses metadata labels to select the application
and database containers.

## Cross-project log collection

Required application Compose labels:

```yaml
labels:
  hirkanet_log_role: application
```

Required database Compose label:

```yaml
labels:
  hirkanet_log_role: database
```

Filebeat obtains container labels through a restricted Docker socket proxy. The
Filebeat container does not mount `/var/run/docker.sock` directly.

Both projects must run on the same Docker host for the supplied Filebeat paths:

```text
/var/lib/docker/containers/*/*.log
```

## Recommended startup order

Validate host prerequisite:

```bash
sysctl vm.max_map_count
```

Start the application stack:

```bash
docker compose up -d --build
```

Start the observability stack:

```bash
docker compose -f docker-compose.elastic.yml up -d --build
```

Run the ingestion verification:

```bash
./elk/verify-ingestion.sh
```

The stacks can be restarted and upgraded independently.

## Configuration validation

```bash
docker compose config
docker compose -f docker-compose.elastic.yml config
```

Run the focused configuration tests:

```bash
pytest -q \
  tests/test_elastic_stack_configuration.py \
  tests/test_full_tls_hostname_verification.py \
  tests/test_elastic_certificate_rotation.py \
  tests/test_elastic_ingestion_pipeline.py \
  tests/test_compose_network_segmentation.py \
  tests/test_compose_resource_limits.py \
  tests/test_compose_health_checks.py \
  tests/test_compose_split.py
```

## Persistent volumes

Application data volumes and bind mounts are controlled by
`docker-compose.yml`.

Elastic data volumes:

```text
es_data
kibana_data
logstash_data
filebeat_data
```

Elastic certificate volumes:

```text
legacy_elastic_certs
elastic_ca_private
elastic_ca_public
elasticsearch_certs
kibana_certs
logstash_certs
```

The legacy volume is used only by the one-time certificate migration job. It is
not mounted into runtime Elastic services.

## Safe upgrades

Application stack:

```bash
docker compose up -d --build --force-recreate
```

Observability stack:

```bash
docker compose -f docker-compose.elastic.yml up -d --build --force-recreate
```

These commands preserve named volumes.

## Destructive cleanup

The following commands delete persistent data and must not be used during a
normal restart or upgrade:

```bash
docker compose down -v
docker compose -f docker-compose.elastic.yml down -v
```

Use `-v` only when permanent deletion of the corresponding database or Elastic
indices is explicitly intended.
