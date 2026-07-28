# Hirkanet Logging and Elastic Stack Guide

This project emits structured JSON application, HTTP, audit, collector, and error events to stdout. Docker captures stdout; Filebeat reads only the Hirkanet app and PostgreSQL containers; Logstash parses and enriches records; Elasticsearch stores them under an ILM-managed alias; Kibana provides search, dashboards, and alerts.

## Main files

- `logging_config.py`: JSON formatting, secret redaction, request IDs, request duration.
- `api/app.py`: logging initialization, authentication events, readiness and exception events.
- `gunicorn_logging.py`: structured Gunicorn access logs.
- `client/routes.py`: policy evaluation and batch evaluation events.
- `admin/routes.py`: administrative audit events and secure password handling.
- `collectors/fortigate_collector.py`: collector operational logs.
- `elk/filebeat/filebeat.yml`: Docker filestream input and container filtering.
- `elk/logstash/pipeline/logstash.conf`: JSON parsing, failure routing, TLS Elasticsearch output.
- `elk/setup-ilm.sh`: 30-day lifecycle policy.
- `docker-compose.yml`: secured Elastic stack, certificates, loopback bindings, health checks.

## Start

1. Copy `.env.example` to `.env` and replace every placeholder.
2. Set `vm.max_map_count=262144` on Linux.
3. Run `docker compose up -d --build`.
4. Run the ILM setup command documented in `ELK-SETUP.md`.
5. Open Kibana at `https://localhost:5601` through your local browser/proxy configuration.

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

Use `debug` for diagnostics, `info` for normal business events, `warning` for recoverable anomalies, `error` for failed operations, and `exception` inside exception handlers. Never log credentials, tokens, cookies, raw authorization headers, password material, or complete sensitive payloads.

## Kibana examples

- Errors: `service.name: "hirkanet" and log.level: ("error" or "critical")`
- Authentication failures: `event_type: "authentication_failure"`
- Policy failures: `event_type: "policy_evaluation_failure"`
- Slow requests: `event.duration > 1000000000`
- One request: `request.id: "<request-id>"`
- Parse failures: `tags: "hirkanet_json_parse_failure"`
