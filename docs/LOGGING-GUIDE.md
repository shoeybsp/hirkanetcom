# Hirkanet Logging and Elastic Stack Guide

Hirkanet emits structured application, HTTP, audit, collector, and error events as JSON on stdout. Docker captures those records, Filebeat reads only the Hirkanet application and PostgreSQL containers, Logstash parses and enriches them, and Elasticsearch stores valid events through the ILM-managed `hirkanet-logs` rollover alias.

## Secured data path

```text
Hirkanet/PostgreSQL stdout
          ↓
Docker json-file logs
          ↓
Filebeat --TLS--> Logstash --HTTPS--> Elasticsearch
                                      ↑
                           Kibana --HTTPS
```

The first Compose startup generates a private CA plus certificates for Elasticsearch, Logstash, and Kibana. All Elastic services use the same `STACK_VERSION`.

## Main files

- `logging_config.py`: JSON formatting, secret redaction, request IDs, and request duration.
- `api/app.py`: logging initialization, authentication events, readiness, and exception events.
- `gunicorn_logging.py`: structured Gunicorn access logs.
- `client/routes.py`: policy evaluation and batch evaluation events.
- `admin/routes.py`: administrative audit events and secure password handling.
- `collectors/fortigate_collector.py`: collector operational logs.
- `elk/filebeat/filebeat.yml`: Docker filestream input, container filtering, and TLS Logstash output.
- `elk/logstash/pipeline/logstash.conf`: TLS Beats input, JSON parsing, dead-letter routing, HTTPS Elasticsearch output, and ILM alias configuration.
- `elk/setup-ilm.sh`: idempotent ILM policy, index template, and initial rollover-index setup.
- `docker-compose.elastic.yml`: certificate generation, secured Elastic services, loopback bindings, and health checks.
- `ELK-SETUP.md`: deployment, trust, verification, rotation, and troubleshooting procedures.

## Start

1. Configure all required secrets in `.env`.
2. Set `vm.max_map_count=262144` on Linux.
3. Run `docker compose -f docker-compose.elastic.yml up -d`.
4. Wait for `elastic-init` to complete successfully.
5. Open Kibana at `https://127.0.0.1:5601`.

ILM installation is automatic. Do not run a separate unsecured or HTTP-based setup command.

## Indexing and retention

Normal events are written through the `hirkanet-logs` alias. The lifecycle policy rolls the write index at 10 GB primary-shard size or one day of age and deletes rolled indices after 30 days.

Malformed Hirkanet JSON records are routed through the `hirkanet-dead-letter` rollover alias. They use the separate `hirkanet-dead-letter-policy`: rollover at 5 GB or 7 days, then deletion 30 days after rollover. This keeps parse failures isolated and bounded.

## Application logging

```python
import logging

logger = logging.getLogger(__name__)
logger.info(
    "Policy evaluation completed",
    extra={
        "event_type": "policy_evaluation_completed",
        "user_id": str(current_user.id),
        "result_count": len(results),
        "event_duration": duration_ns,
    },
)
```

Use `debug` for diagnostics, `info` for normal business events, `warning` for recoverable anomalies, `error` for failed operations, and `exception` inside exception handlers.

Never log credentials, tokens, cookies, authorization headers, password material, private keys, or complete sensitive request payloads.

## Kibana examples

- Errors: `service.name: "hirkanet" and log.level: ("error" or "critical")`
- Authentication failures: `event_type: "authentication_failure"`
- Policy failures: `event_type: "policy_evaluation_failure"`
- Slow requests: `event.duration > 1000000000`
- One request: `request.id: "<request-id>"`
- Parse failures: `tags: "hirkanet_json_parse_failure"`

See `ELK-SETUP.md` for CA export, HTTPS commands, ILM verification, and certificate rotation.

## TLS identity verification

The logging path uses full hostname verification, not CA-only verification. Filebeat connects to `logstash`, while Logstash and Kibana connect to `elasticsearch`; those exact DNS identities are present in the generated service certificates. A certificate signed by the Hirkanet CA is rejected when its SAN does not match the requested hostname.

When changing Compose service names, DNS aliases, or endpoints, update the certificate instance definitions and reissue only the affected service certificates from the existing CA. Do not disable hostname checks to make a renamed endpoint connect.
