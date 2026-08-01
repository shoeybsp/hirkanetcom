# Hirkanet Elastic Stack Setup

Hirkanet deploys Elasticsearch, Logstash, Kibana, and Filebeat with authentication and TLS enabled. A private certificate authority and service certificates are generated in the `elastic_certs` Docker volume only during the initial bootstrap. Subsequent startups must reuse that trust root and will fail closed if the CA material is incomplete.

## Prerequisites

- Docker Engine and Docker Compose v2
- Linux host setting: `sudo sysctl -w vm.max_map_count=262144`
- At least 4 GB of free RAM for the complete stack
- Strong values for all Elastic and Kibana secrets in `.env`

The Elastic images use one version through `STACK_VERSION`. Filebeat no longer has a separate version setting.

## Required environment values

Set these values in `.env` before starting the stack:

```dotenv
STACK_VERSION=9.3.8
ELASTIC_PASSWORD=replace-with-a-strong-password
KIBANA_PASSWORD=replace-with-a-different-strong-password
LOGSTASH_PASSWORD=replace-with-a-different-strong-password
KIBANA_SECURITY_ENCRYPTION_KEY=at-least-32-characters-long
KIBANA_SAVED_OBJECTS_ENCRYPTION_KEY=at-least-32-characters-long
KIBANA_REPORTING_ENCRYPTION_KEY=at-least-32-characters-long
```

Generate secrets, for example:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not commit `.env` or exported private keys.

## Start the stack

```bash
docker compose -f docker-compose.elastic.yml up -d
```

The startup sequence automatically:

1. Creates the private CA only when no CA has ever been initialized, then issues service certificates from that CA.
2. Starts Elasticsearch with HTTPS and encrypted transport traffic.
3. Creates the `kibana_system` and Logstash credentials.
4. Installs separate ILM policies for normal logs and dead-letter events.
5. Installs the matching index template.
6. Creates `hirkanet-logs-000001` with `hirkanet-logs` as its write alias.
7. Starts TLS-protected Logstash, Kibana, and Filebeat connections.

No separate ILM installation command is required.

Check startup status:

```bash
docker compose -f docker-compose.elastic.yml ps
docker compose -f docker-compose.elastic.yml logs --tail=100 \
  elastic-certs-setup elasticsearch elastic-init logstash kibana filebeat
```

## TLS topology

```text
Filebeat --TLS--> Logstash --TLS/HTTPS--> Elasticsearch
                                  ^
Kibana -----------HTTPS-----------|
Browser ----------HTTPS----------> Kibana
```

Certificates are stored only in the `elastic_certs` Docker volume. Elasticsearch, Logstash, Kibana, and Filebeat mount that volume read-only.

## Access Elasticsearch

Export only the CA certificate when command-line clients need to trust the stack:

```bash
docker compose -f docker-compose.elastic.yml cp \
  elasticsearch:/usr/share/elasticsearch/config/certs/ca/ca.crt \
  ./hirkanet-elastic-ca.crt
```

Then query Elasticsearch:

```bash
curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  https://127.0.0.1:9200/_cluster/health?pretty
```

The CA certificate is public trust material. Never export or distribute `ca.key` or service private keys.

## Access Kibana

Open:

```text
https://127.0.0.1:5601
```

Sign in as `elastic` using the value stored in `secrets/elastic_password`.

The browser will not trust Hirkanet's private CA by default. Import `hirkanet-elastic-ca.crt` into the local trust store, or accept the warning only in a controlled development environment.

Create a data view for:

```text
hirkanet-logs*
```

Use `@timestamp` as the time field.

## ILM behavior

Normal events are written through the `hirkanet-logs` alias. Elasticsearch rolls the index when either condition is reached:

- Primary shard size reaches 10 GB
- Index age reaches one day

Rolled indices are deleted after 30 days.

Verify the lifecycle configuration:

```bash
curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  https://127.0.0.1:9200/_ilm/policy/hirkanet-logs-policy?pretty

curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  https://127.0.0.1:9200/_alias/hirkanet-logs?pretty

curl --cacert ./hirkanet-elastic-ca.crt \
  -u "elastic:$(cat secrets/elastic_password)" \
  https://127.0.0.1:9200/hirkanet-logs-*/_ilm/explain?pretty
```

Application JSON parse failures are routed through the separate `hirkanet-dead-letter` rollover alias. The `hirkanet-dead-letter-policy` rolls over at 5 GB or 7 days and deletes rolled indices after 30 days, independently of normal application logs.

## Certificate lifecycle and explicit rotation

### Normal startup behavior

The `elastic-certs-setup` service never silently replaces an existing trust root.

- If both `ca/ca.crt` and `ca/ca.key` are absent, the stack treats this as first-time bootstrap and creates the initial CA.
- If both CA files exist, they are reused.
- If only one CA file exists, startup fails. Restore the missing CA material from backup or perform an explicit trust-root rotation.
- If a service certificate is missing, the service certificate set is reissued using the existing CA. The CA itself is not replaced.

The CA private key remains inside the protected `elastic_certs` Docker volume with mode `0600`. Do not export it to clients. Back up the Docker volume using an encrypted, access-controlled backup process.

### Service-certificate renewal without CA rotation

To renew service certificates while preserving client trust, remove only the service-certificate directories from the certificate volume, retain `ca/ca.crt` and `ca/ca.key`, and rerun `elastic-certs-setup`. This operation should be performed under change control and after a verified backup.

### Explicit trust-root rotation

Trust-root rotation is disruptive: all previously exported CA certificates become invalid. Use the supplied guarded command only after scheduling client redistribution:

```bash
./elk/rotate-elastic-ca.sh --confirm-trust-root-rotation
```

The script:

1. Requires the exact confirmation flag.
2. Saves the old public CA and SHA-256 fingerprint when available.
3. Stops the Elastic services.
4. Removes the `elastic_certs` volume explicitly.
5. Creates a new CA and new service certificates.
6. Exports the new public CA and fingerprint.
7. Prints the required client-migration steps.

After rotation, redistribute the new CA to browsers, command-line clients, monitoring systems, and integrations. Verify all stack health checks, remove the old CA only after migration, and record the new fingerprint in change management.

Never rotate the CA merely because a service certificate is missing. Reissue service certificates from the existing CA instead.

## Troubleshooting

### Certificate setup fails

```bash
docker compose -f docker-compose.elastic.yml logs elastic-certs-setup
```

Confirm the certificate volume is writable and that all Elastic images use the same `STACK_VERSION`. If the log reports incomplete CA material, do not delete the volume casually; restore the CA backup or run the documented explicit trust-root rotation procedure.

### Logstash cannot connect to Elasticsearch

```bash
docker compose -f docker-compose.elastic.yml logs logstash elastic-init elasticsearch
```

Check `secrets/logstash_password`, its Docker secret mount, CA mounts, and the `logstash_internal` user initialization.

### Filebeat cannot connect to Logstash

```bash
docker compose -f docker-compose.elastic.yml logs filebeat logstash
```

Confirm both services mount `elastic_certs` and that Logstash is listening on TLS port `5044`.

### ILM does not roll over

Confirm that Logstash writes to the `hirkanet-logs` alias rather than directly to a date-based index, then inspect `_ilm/explain` using the command above.

## Full TLS hostname verification

All supported Elastic connections use full certificate verification. A trusted CA alone is not sufficient: the certificate identity must also match the hostname used by the client.

The generated certificate SANs and runtime hostnames are aligned as follows:

| Connection | Client hostname | Required certificate SAN |
|---|---|---|
| Filebeat → Logstash | `logstash` | DNS `logstash` |
| Logstash → Elasticsearch | `elasticsearch` | DNS `elasticsearch` |
| Kibana → Elasticsearch | `elasticsearch` | DNS `elasticsearch` |
| Elastic initialization → Elasticsearch | `elasticsearch` | DNS `elasticsearch` |
| Local Elasticsearch health check | `127.0.0.1` | IP `127.0.0.1` |
| Local Kibana health check | `127.0.0.1` | IP `127.0.0.1` |

The configuration therefore uses `full` verification for Filebeat, Logstash's Elasticsearch outputs, Kibana, and Elasticsearch transport TLS. Do not replace service DNS names with arbitrary aliases or container IP addresses unless those identities are added to the corresponding certificate SANs and the certificates are deliberately reissued.

A hostname mismatch must be corrected by fixing the endpoint name or reissuing the service certificate from the existing CA. Do not weaken verification to `certificate` or `none` as a workaround.
