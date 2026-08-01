from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP_COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
ELASTIC_COMPOSE = yaml.safe_load(
    (ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8")
)
SERVICES = {**APP_COMPOSE["services"], **ELASTIC_COMPOSE["services"]}


def health_command(service_name: str) -> str:
    test = SERVICES[service_name]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    return test[1]


def test_runtime_services_have_healthchecks():
    for service_name in (
        "db",
        "app",
        "elasticsearch",
        "logstash",
        "kibana",
        "docker-socket-proxy",
        "filebeat",
    ):
        assert "healthcheck" in SERVICES[service_name], (
            f"{service_name} must have a healthcheck"
        )


def test_postgres_healthcheck_executes_authenticated_query():
    command = health_command("db")
    assert "psql" in command
    assert "SELECT 1" in command
    assert "/run/secrets/postgres_password" in command
    assert "pg_isready" not in command


def test_application_healthcheck_uses_database_backed_readiness_endpoint():
    command = health_command("app")
    assert "/readyz" in command
    assert "/livez" not in command


def test_elasticsearch_healthcheck_requires_ready_cluster():
    command = health_command("elasticsearch")
    assert "/_cluster/health" in command
    assert "wait_for_status=yellow" in command
    assert '"timed_out":false' in command
    assert '"status":"(yellow|green)"' in command


def test_logstash_healthcheck_uses_node_pipeline_api():
    command = health_command("logstash")
    assert "http://127.0.0.1:9600/_node/pipelines" in command
    assert 'key?("main")' in command
    assert "/dev/tcp" not in command
    assert SERVICES["logstash"]["environment"]["API_HTTP_HOST"] == "127.0.0.1"


def test_kibana_healthcheck_requires_available_status():
    command = health_command("kibana")
    assert "/api/status" in command
    assert '"level":"available"' in command


def test_socket_proxy_healthcheck_uses_read_only_ping_endpoint():
    command = health_command("docker-socket-proxy")
    assert "/_ping" in command
    assert SERVICES["docker-socket-proxy"]["environment"]["POST"] == "0"


def test_filebeat_healthcheck_validates_tls_output_connection():
    command = health_command("filebeat")
    assert "filebeat test output" in command
    assert "/dev/tcp" not in command
