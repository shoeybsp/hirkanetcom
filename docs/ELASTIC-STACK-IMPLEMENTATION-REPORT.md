# Elastic Stack Four-Phase Implementation Report

Date: 2026-08-01

## Scope

This implementation applies the four remediation phases from the Elastic Stack
review to:

- Docker Compose orchestration
- Elasticsearch
- Logstash
- Kibana
- Filebeat
- TLS certificate bootstrap and rotation
- ILM policies, templates, and aliases
- Docker metadata access
- Elastic documentation and tests

No application business logic, PostgreSQL schema, FortiGate collection logic,
or existing Elastic data volume was intentionally modified.

## Final status

All four phases are implemented in code and documentation.

Static validation completed successfully:

```text
YAML validation: passed
Shell syntax validation: passed
Focused Elastic/configuration tests: 53 passed
Full project test suite: 132 passed
```

A Docker daemon was not available in the implementation environment. Therefore,
image pulls, `docker compose config`, container startup, Logstash's native
`--config.test_and_exit`, Filebeat's native tests, and the synthetic ingestion
script must be executed on the deployment host.

---

# Phase 1 — Deterministic startup

## Objective

Remove the startup blockers that prevented the complete stack from starting in
its dependency order.

## Implemented changes

### Certificate startup order

Added one-shot services and scripts:

```text
elastic-certs-migrate
elastic-certs-setup
openssl-helper
```

Startup now guarantees:

1. Previous certificate material is migrated before certificate validation.
2. CA validation/generation finishes before service startup.
3. Logstash PEM key generation finishes before PKCS#8 conversion.
4. Logstash starts only after PKCS#8 conversion and Elastic initialization.

The old race where `openssl-helper` could execute before
`logstash/logstash.key` existed is removed.

### Fail-closed CA lifecycle

`elk/setup-certs.sh` now distinguishes three states:

| CA state | Result |
|---|---|
| `ca.crt` and `ca.key` both absent | Create initial CA |
| Both present | Reuse existing CA |
| Exactly one present | Stop with an explicit error |

The stack no longer silently deletes partial CA material or replaces the trust
root during normal startup.

### Existing CA preservation during upgrade

`elk/migrate-legacy-certs.sh` migrates the existing
`hirkanet-observability_elastic_certs` volume into the new split volumes when:

- the legacy CA is complete; and
- the new CA volume is empty.

This prevents an accidental CA rotation when deploying the new Compose file over
an existing installation.

### Logstash credential mismatch

The pipeline previously referenced:

```text
LOGSTASH_INTERNAL_PASSWORD
```

while Compose exported:

```text
LOGSTASH_PASSWORD
```

Both orchestration and pipeline configuration now consistently use
`LOGSTASH_PASSWORD`.

### Host-access networking

Added a dedicated non-internal network:

```text
elastic-access
```

Only Elasticsearch and Kibana join this network. Their published ports remain
restricted to loopback:

```text
127.0.0.1:9200
127.0.0.1:5601
```

Private service communication remains on internal networks.

### Elasticsearch host prerequisite

Documentation now requires:

```text
vm.max_map_count=1048576
```

The obsolete `262144` recommendation was removed.

### Elasticsearch runtime limits

Added:

- memory locking
- unlimited memlock ulimit
- `nofile` soft/hard limit of `65535`

### Official image locations

All Elastic products now use the official Elastic registry and the same
`STACK_VERSION` value:

```text
docker.elastic.co/elasticsearch/elasticsearch
docker.elastic.co/logstash/logstash
docker.elastic.co/kibana/kibana
docker.elastic.co/beats/filebeat
```

## Phase 1 files

```text
docker-compose.elastic.yml
elk/migrate-legacy-certs.sh
elk/setup-certs.sh
elk/convert-logstash-key.sh
elk/openssl-helper/Dockerfile
```

---

# Phase 2 — Correct ingestion and ILM

## Objective

Correct event parsing, remove duplicate indexing, implement real dead-letter
routing, and make ILM rollover aliases functional.

## Implemented changes

### Application JSON parsing

Logstash now selects application events using:

```text
container.labels.hirkanet_log_role = application
```

It parses the Docker `message` field as JSON and preserves the original line in:

```text
event.original
```

### ECS-compatible field copies

The pipeline copies existing application fields into normalized searchable
locations:

| Existing field | Normalized field |
|---|---|
| `event_type` | `event.type` |
| `event_duration` | `event.duration` |
| `http_status_code` | `http.response.status_code` |
| `user_id` | `user.id` |

Existing fields are retained for query compatibility.

### PostgreSQL event handling

Database events are not passed through the application JSON parser. Logstash
adds:

```text
service.name = postgresql
event.dataset = postgresql.log
event.kind = event
```

### Conditional dead-letter routing

The two Elasticsearch outputs are now mutually exclusive:

- valid application events and database events -> `hirkanet-logs`
- malformed application JSON -> `hirkanet-dead-letter`

The previous unconditional second output, which duplicated every event into the
dead-letter index, was removed.

Parse-failure records include:

```text
event.dataset = hirkanet.dead_letter
event.kind = pipeline_error
error.type = json_parse_failure
error.message = Application container log line was not valid JSON
```

### Explicit ILM configuration

Both Logstash outputs now explicitly configure:

```text
ilm_enabled
ilm_rollover_alias
ilm_pattern
ilm_policy
```

Normal logs:

```text
alias:  hirkanet-logs
policy: hirkanet-logs-policy
```

Dead-letter logs:

```text
alias:  hirkanet-dead-letter
policy: hirkanet-dead-letter-policy
```

Date-based direct index writes were removed.

### Idempotent ILM bootstrap

`elk/setup-ilm.sh` now:

- creates or updates both policies;
- creates or updates both index templates;
- configures single-node replica counts;
- installs mappings for key fields;
- creates the initial write index when absent;
- restores the write alias if the initial index exists without it;
- remains safe to run repeatedly.

### End-to-end synthetic test

Added:

```text
elk/verify-ingestion.sh
```

It emits one valid and one malformed labeled application event and verifies:

- valid event exists in normal indices;
- valid event does not exist in dead-letter indices;
- malformed event does not exist in normal indices;
- malformed event exists in dead-letter indices.

## Phase 2 files

```text
elk/logstash/pipeline/logstash.conf
elk/filebeat/filebeat.yml
elk/setup-ilm.sh
elk/verify-ingestion.sh
```

---

# Phase 3 — TLS, image, and runtime hardening

## Objective

Reduce private-key exposure, improve certificate operations, pin helper images,
and restrict Docker socket access.

## Implemented changes

### Split certificate volumes

The previous shared `elastic_certs` runtime mount was replaced by:

```text
elastic_ca_private
elastic_ca_public
elasticsearch_certs
kibana_certs
logstash_certs
```

Runtime access is now limited:

| Service | Certificate access |
|---|---|
| Elasticsearch | public CA + Elasticsearch certificate/key |
| Kibana | public CA + Kibana certificate/key |
| Logstash | public CA + Logstash certificate/keys |
| Filebeat | public CA only |
| Elastic initialization | public CA only |

The CA private key is mounted only into one-shot certificate jobs.

### Public CA sanitization

The setup script explicitly removes any `ca.key` from the public CA volume and
ensures that volume contains only public trust material.

### Build-time OpenSSL helper

Replaced:

```text
alpine:latest + runtime apk add
```

with a project helper image built from:

```text
alpine:3.21.3
```

OpenSSL is installed during the image build.

### Restricted Docker socket proxy

Filebeat no longer mounts `/var/run/docker.sock`.

Added:

```text
docker-socket-proxy
```

The proxy is isolated on an internal network and permits only read-only API
sections required for container metadata:

```text
CONTAINERS
EVENTS
INFO
PING
VERSION
```

HTTP POST and all unrelated Docker API sections remain denied.

The proxy port is not published to the host.

### Corrected CA rotation

The previous rotation flow stopped containers but left them attached to the
certificate volume before attempting removal.

The new script:

1. resolves actual Compose volume names;
2. backs up the old public CA and fingerprint;
3. runs `docker compose down --remove-orphans`;
4. removes certificate volumes only;
5. preserves Elasticsearch/Kibana/Logstash/Filebeat data volumes;
6. rebuilds and starts the stack;
7. waits for Elasticsearch health;
8. exports the new public CA and fingerprint.

The legacy certificate volume is also removed during explicit rotation so it
cannot restore the old CA.

### Full TLS verification

Full hostname verification is explicit for:

- Filebeat -> Logstash
- Logstash -> Elasticsearch
- Kibana -> Elasticsearch
- Elasticsearch transport TLS

Generated certificate SANs match runtime Docker hostnames and loopback health
checks.

## Phase 3 files

```text
docker-compose.elastic.yml
elk/setup-certs.sh
elk/migrate-legacy-certs.sh
elk/convert-logstash-key.sh
elk/openssl-helper/Dockerfile
elk/rotate-elastic-ca.sh
elk/filebeat/filebeat.yml
elk/logstash/pipeline/logstash.conf
```

---

# Phase 4 — Documentation and tests

## Objective

Make operational documentation and tests reflect the implemented stack rather
than the previous intended design.

## Documentation changes

### `ELK-SETUP.md`

Now documents:

- current host prerequisites;
- Docker secret files;
- image and version policy;
- certificate-volume separation;
- legacy certificate migration;
- deterministic startup order;
- native Logstash and Filebeat validation commands;
- synthetic ingestion verification;
- ILM behavior;
- restricted Docker metadata access;
- service-certificate renewal;
- explicit CA rotation;
- troubleshooting sequence.

### `LOGGING-GUIDE.md`

Now documents the actual:

- application JSON parsing;
- normalized fields;
- PostgreSQL classification;
- conditional dead-letter behavior;
- ILM aliases;
- Kibana data views and queries;
- runtime verification procedure.

### `COMPOSE-DEPLOYMENT.md`

Now documents:

- all one-shot and runtime services;
- four observability networks;
- loopback-only host access;
- socket-proxy architecture;
- persistent data and certificate volumes;
- safe upgrade commands;
- destructive cleanup warnings.

### `.env.example`

Added a safe template containing non-secret application, Elastic version/JVM,
storage monitoring, and retention settings. It does not contain real secret
values.

## Test changes

Tests now validate parsed YAML and operational behavior instead of relying only
on exact formatting.

Added or expanded coverage for:

- startup dependency order;
- official images and pinned helper bases;
- Logstash password consistency;
- conditional normal/dead-letter outputs;
- explicit ILM aliases and policies;
- legacy CA migration;
- split private-key mounts;
- PKCS#8 ordering;
- CA rotation order;
- socket-proxy permissions;
- Filebeat's lack of direct socket access;
- host-access network separation;
- synthetic ingestion script behavior;
- documentation/Compose alignment.

The unrelated multiline `read_secret()` source check was made whitespace-safe so
it tests behavior rather than one-line formatting.

## Phase 4 files

```text
.env.example
ELK-SETUP.md
LOGGING-GUIDE.md
COMPOSE-DEPLOYMENT.md
tests/test_elastic_stack_configuration.py
tests/test_full_tls_hostname_verification.py
tests/test_elastic_certificate_rotation.py
tests/test_elastic_ingestion_pipeline.py
tests/test_compose_network_segmentation.py
tests/test_compose_health_checks.py
tests/test_compose_split.py
tests/test_secret_configuration.py
```

---

# Deployment procedure

## 1. Back up

Back up the repository and Elastic data volumes before replacement.

Do not delete the existing legacy certificate volume. The migration job uses it
to preserve the current CA.

## 2. Replace files

Extract the supplied changed-files archive into the project root while
preserving directories.

## 3. Set host prerequisite

```bash
sudo sysctl -w vm.max_map_count=1048576
```

## 4. Validate Compose

```bash
docker compose -f docker-compose.elastic.yml config
```

## 5. Build and start

```bash
docker compose -f docker-compose.elastic.yml up -d --build
```

Do not add `-v` to `down` commands.

## 6. Inspect startup

```bash
docker compose -f docker-compose.elastic.yml ps -a

docker compose -f docker-compose.elastic.yml logs --tail=200 \
  elastic-certs-migrate elastic-certs-setup openssl-helper \
  elasticsearch elastic-init logstash kibana docker-socket-proxy filebeat
```

## 7. Native config validation

```bash
docker compose -f docker-compose.elastic.yml run --rm --no-deps \
  --entrypoint /bin/bash logstash -ec '
    export LOGSTASH_PASSWORD="$(cat /run/secrets/logstash_password)"
    /usr/share/logstash/bin/logstash \
      --config.test_and_exit \
      -f /usr/share/logstash/pipeline/logstash.conf
  '

docker compose -f docker-compose.elastic.yml exec filebeat \
  filebeat test config -e --strict.perms=false

docker compose -f docker-compose.elastic.yml exec filebeat \
  filebeat test output -e --strict.perms=false
```

## 8. End-to-end validation

```bash
./elk/verify-ingestion.sh
```

## 9. Access

```text
Elasticsearch: https://127.0.0.1:9200
Kibana:        https://127.0.0.1:5601
```

---

# Rollback considerations

The new Compose file can migrate the previous CA into split volumes, but the
reverse migration is not automatic.

Before deployment, retain:

- the previous Compose/configuration files;
- a backup of `hirkanet-observability_elastic_certs`;
- backups of Elastic data volumes.

If rollback is required before ingestion resumes, restore the previous files and
legacy certificate volume. Do not run either version with `down -v` unless data
deletion is intended.

---

# Remaining runtime checks

These checks require the actual Docker host and remain mandatory:

1. `docker compose ... config`
2. image build and pull
3. certificate migration against the real legacy volume
4. complete startup and health checks
5. Logstash native config test
6. Filebeat native config/output tests
7. synthetic normal/dead-letter ingestion test
8. browser/CLI trust using the preserved or newly generated CA
9. ILM rollover and retention observation over time

---

# Reference basis

Implementation decisions were checked against current primary documentation:

- Elastic production Docker requirements:
  https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-prod
- Logstash Elasticsearch output and ILM:
  https://www.elastic.co/docs/reference/logstash/plugins/plugins-outputs-elasticsearch
- Filebeat Docker metadata processor:
  https://www.elastic.co/docs/reference/beats/filebeat/add-docker-metadata
- Kibana encrypted saved objects:
  https://www.elastic.co/docs/deploy-manage/security/secure-saved-objects
- Docker socket proxy project and permission model:
  https://github.com/Tecnativa/docker-socket-proxy
