# Hirkanet Elastic Stack Setup

Hirkanet deploys Elasticsearch, Logstash, Kibana, and Filebeat as a separate
Compose project named `hirkanet-observability`. Authentication and TLS are
required on every supported Elastic connection.

## Prerequisites

- Docker Engine and Docker Compose v2
- At least 4 GB of available RAM for the complete stack
- Linux `vm.max_map_count` set to `1048576`
- Strong secret files under `./secrets`

Set and persist the required Linux kernel value:

```bash
sudo sysctl -w vm.max_map_count=1048576
printf 'vm.max_map_count=1048576\n' | sudo tee /etc/sysctl.d/99-elasticsearch.conf
sudo sysctl --system
```

Verify it:

```bash
sysctl vm.max_map_count
```

Expected:

```text
vm.max_map_count = 1048576
```

Elastic requires `1048576` for current Elasticsearch releases. Do not use the
older `262144` value for this stack.

## Versions and non-secret environment settings

The four Elastic products use one version variable:

```dotenv
STACK_VERSION=9.3.8
TZ=Europe/Riga
ES_JAVA_OPTS=-Xms512m -Xmx512m
LS_JAVA_OPTS=-Xms256m -Xmx256m
```

The Compose file uses the official Elastic registry:

- `docker.elastic.co/elasticsearch/elasticsearch`
- `docker.elastic.co/logstash/logstash`
- `docker.elastic.co/kibana/kibana`
- `docker.elastic.co/beats/filebeat`

The OpenSSL helper is built from the pinned `alpine:3.21.3` base image. OpenSSL
is installed at image build time, not every time the stack starts.

## Required secret files

The stack reads credentials from Docker Compose secret files, not plaintext
Compose environment variables:

```text
secrets/elastic_password
secrets/kibana_password
secrets/logstash_password
secrets/kibana_security_encryption_key
secrets/kibana_saved_objects_encryption_key
secrets/kibana_reporting_encryption_key
```

Generate new values with restrictive permissions:

```bash
umask 077
openssl rand -base64 48 > secrets/elastic_password
openssl rand -base64 48 > secrets/kibana_password
openssl rand -base64 48 > secrets/logstash_password
openssl rand -base64 48 > secrets/kibana_security_encryption_key
openssl rand -base64 48 > secrets/kibana_saved_objects_encryption_key
openssl rand -base64 48 > secrets/kibana_reporting_encryption_key
chmod 600 secrets/*
```

Kibana encryption keys must remain stable. Changing them can make existing
sessions, reports, and encrypted saved objects unreadable.

## Certificate architecture

Private key access is separated across Docker volumes:

| Volume | Contents | Runtime consumers |
|---|---|---|
| `elastic_ca_private` | CA certificate and CA private key | Certificate jobs only |
| `elastic_ca_public` | Public CA certificate only | Elasticsearch, initialization, Logstash, Kibana, Filebeat |
| `elasticsearch_certs` | Elasticsearch certificate and private key | Elasticsearch only |
| `kibana_certs` | Kibana certificate and private key | Kibana only |
| `logstash_certs` | Logstash certificate and private keys | Logstash and one-shot OpenSSL helper |

Filebeat does not receive a service private key. It receives only the public CA
certificate needed to verify Logstash.

### Upgrade from the previous single certificate volume

The one-shot `elastic-certs-migrate` job checks the previous volume named:

```text
hirkanet-observability_elastic_certs
```

When that volume contains a complete CA and the new split volumes are empty,
the job copies the existing CA and service certificates into the split volumes.
This preserves the existing trust root and avoids silently invalidating exported
CA certificates.

Migration fails closed when the legacy CA contains only one of `ca.crt` or
`ca.key`.

## Deterministic startup order

The Compose dependency chain is:

```text
elastic-certs-migrate
  -> elastic-certs-setup
      -> openssl-helper
      -> elasticsearch
          -> elastic-init
              -> logstash
              -> kibana
                  -> filebeat
```

Important behaviors:

1. Legacy certificates are migrated only when the new CA volume is empty.
2. A CA is created only when both CA files are absent.
3. Exactly one missing CA file stops startup.
4. Missing service certificates are reissued with the existing CA.
5. The Logstash PKCS#8 key is created only after the Logstash PEM key exists.
6. Elasticsearch must become healthy before users, roles, templates, aliases,
   and ILM policies are initialized.
7. Filebeat starts only after Logstash and the restricted Docker socket proxy
   are healthy.

## Validate configuration before startup

Parse the Compose model:

```bash
docker compose -f docker-compose.elastic.yml config >/tmp/hirkanet-elastic-compose.yml
```

Build the pinned OpenSSL helper:

```bash
docker compose -f docker-compose.elastic.yml build openssl-helper
```

Run the repository configuration tests:

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

## Start the stack

```bash
docker compose -f docker-compose.elastic.yml up -d --build
```

Inspect all services, including completed one-shot jobs:

```bash
docker compose -f docker-compose.elastic.yml ps -a
```

Inspect startup logs:

```bash
docker compose -f docker-compose.elastic.yml logs --tail=200 \
  elastic-certs-migrate \
  elastic-certs-setup \
  openssl-helper \
  elasticsearch \
  elastic-init \
  logstash \
  kibana \
  docker-socket-proxy \
  filebeat
```

Expected state:

- `elastic-certs-migrate`: exited `0`
- `elastic-certs-setup`: exited `0`
- `openssl-helper`: exited `0`
- `elastic-init`: exited `0`
- `elasticsearch`: healthy
- `logstash`: healthy
- `kibana`: healthy
- `docker-socket-proxy`: healthy
- `filebeat`: healthy

## Validate Logstash and Filebeat

Validate the Logstash pipeline without starting the normal service command:

```bash
docker compose -f docker-compose.elastic.yml run --rm --no-deps \
  --entrypoint /bin/bash logstash -ec '
    export LOGSTASH_PASSWORD="$(cat /run/secrets/logstash_password)"
    /usr/share/logstash/bin/logstash \
      --config.test_and_exit \
      -f /usr/share/logstash/pipeline/logstash.conf
  '
```

Validate Filebeat configuration and its TLS output:

```bash
docker compose -f docker-compose.elastic.yml exec filebeat \
  filebeat test config -e --strict.perms=false

docker compose -f docker-compose.elastic.yml exec filebeat \
  filebeat test output -e --strict.perms=false
```

## End-to-end ingestion verification

Run the supplied synthetic verification after the stack is healthy:

```bash
./elk/verify-ingestion.sh
```

The script creates two temporary, labeled Docker containers:

- one emits valid Hirkanet application JSON;
- one emits malformed application output.

It verifies that:

- valid JSON appears in `hirkanet-logs-*`;
- valid JSON does not appear in `hirkanet-dead-letter-*`;
- malformed JSON does not appear in normal indices;
- malformed JSON appears in `hirkanet-dead-letter-*`.

## TLS topology

```text
Filebeat --TLS/full verification--> Logstash
Logstash --HTTPS/full verification--> Elasticsearch
Kibana   --HTTPS/full verification--> Elasticsearch
Browser  --HTTPS--------------------> Kibana
CLI      --HTTPS--------------------> Elasticsearch
```

Certificate SANs include the Docker service names and localhost addresses used
by health checks:

| Certificate | DNS SANs | IP SAN |
|---|---|---|
| Elasticsearch | `elasticsearch`, `localhost` | `127.0.0.1` |
| Kibana | `kibana`, `localhost` | `127.0.0.1` |
| Logstash | `logstash`, `localhost` | `127.0.0.1` |

## Access Elasticsearch

Elasticsearch is published only on host loopback:

```text
https://127.0.0.1:9200
```

Export the public CA:

```bash
docker compose -f docker-compose.elastic.yml cp \
  elasticsearch:/usr/share/elasticsearch/config/certs/ca/ca.crt \
  ./hirkanet-elastic-ca.crt
```

Query cluster health:

```bash
curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  'https://127.0.0.1:9200/_cluster/health?pretty'
```

Never export `ca.key` or a service private key.

## Access Kibana

Kibana is published only on host loopback:

```text
https://127.0.0.1:5601
```

Sign in as `elastic` using `secrets/elastic_password`. Import
`hirkanet-elastic-ca.crt` into the local trust store to remove browser trust
warnings.

Create data views for:

```text
hirkanet-logs*
hirkanet-dead-letter*
```

Use `@timestamp` as the time field.

## ILM behavior

Logstash explicitly writes through rollover aliases:

- `hirkanet-logs`
- `hirkanet-dead-letter`

Normal logs:

- rollover at 10 GB primary-shard size or one day;
- delete after 30 days.

Dead-letter logs:

- rollover at 5 GB primary-shard size or seven days;
- delete after 30 days.

Verify:

```bash
curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  'https://127.0.0.1:9200/_alias/hirkanet-logs?pretty'

curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  'https://127.0.0.1:9200/hirkanet-logs-*/_ilm/explain?pretty'
```

## Restricted Docker metadata access

Filebeat no longer mounts `/var/run/docker.sock` directly. It calls
`docker-socket-proxy` on an internal-only network.

The proxy permits only read-only Docker API operations required for metadata:

- containers
- events
- info
- ping
- version

HTTP POST requests and all other Docker API sections remain denied. The proxy
port is not published to the host.

On SELinux-enforcing hosts, the Docker socket mount may require an appropriate
label or local policy. Do not solve this by publishing proxy port `2375`.

## Service-certificate renewal without CA rotation

The certificate setup job never silently replaces an existing CA.

To reissue service certificates while preserving client trust:

```bash
docker compose -f docker-compose.elastic.yml down

docker volume rm \
  hirkanet-observability_elasticsearch_certs \
  hirkanet-observability_kibana_certs \
  hirkanet-observability_logstash_certs

docker compose -f docker-compose.elastic.yml up -d --build
```

Do not remove `hirkanet-observability_elastic_ca_private` or
`hirkanet-observability_elastic_ca_public` during service-certificate renewal.

## Explicit trust-root rotation

Trust-root rotation is disruptive. It invalidates every previously exported CA
certificate.

```bash
./elk/rotate-elastic-ca.sh --confirm-trust-root-rotation
```

The script:

1. backs up the old public CA and SHA-256 fingerprint when available;
2. removes containers, not data volumes;
3. removes only certificate volumes, including the legacy certificate volume;
4. rebuilds and starts the stack;
5. waits for Elasticsearch health;
6. exports the new public CA and fingerprint;
7. prints client redistribution requirements.

Never use `docker compose ... down -v` for certificate rotation because it also
removes Elasticsearch, Kibana, Logstash, and Filebeat data volumes.

## Troubleshooting sequence

### Certificate jobs fail

```bash
docker compose -f docker-compose.elastic.yml logs --tail=200 \
  elastic-certs-migrate elastic-certs-setup openssl-helper
```

An incomplete CA is intentionally a hard failure. Restore the missing CA file
or perform an explicit trust-root rotation.

### Elasticsearch fails

```bash
sysctl vm.max_map_count
docker compose -f docker-compose.elastic.yml logs --tail=200 elasticsearch
```

Confirm the value is `1048576`, secrets are non-empty, and certificate jobs
completed successfully.

### Logstash fails

```bash
docker compose -f docker-compose.elastic.yml logs --tail=200 elastic-init logstash
```

Confirm `elastic-init` created `logstash_internal`, the Logstash secret is
mounted, and the PKCS#8 helper exited successfully.

### Filebeat fails

```bash
docker compose -f docker-compose.elastic.yml logs --tail=200 \
  docker-socket-proxy filebeat logstash
```

Confirm Filebeat can reach both `docker-socket-proxy:2375` and
`logstash:5044` on their internal networks.

## Primary references

- Elastic production Docker requirements: https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-prod
- Logstash Elasticsearch output and ILM: https://www.elastic.co/docs/reference/logstash/plugins/plugins-outputs-elasticsearch
- Filebeat Docker metadata processor: https://www.elastic.co/docs/reference/beats/filebeat/add-docker-metadata
- Kibana encrypted saved objects: https://www.elastic.co/docs/deploy-manage/security/secure-saved-objects
- Docker socket proxy: https://github.com/Tecnativa/docker-socket-proxy
