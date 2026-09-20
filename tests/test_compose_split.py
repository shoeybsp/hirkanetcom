from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "docker-compose.yml"
ELASTIC_FILE = ROOT / "docker-compose.elastic.yml"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_application_compose_contains_app_database_and_migration_job():
    compose = load(APP_FILE)
    assert compose["name"] == "hirkanet-app"
    # api_v2 is the additive FastAPI pilot service (docs/architecture.md) -
    # sharing the same database as app/migrate, not replacing them.
    assert set(compose["services"]) == {"app", "db", "migrate", "api_v2"}
    assert set(compose["networks"]) == {"app-db", "frontend"}


def test_elastic_compose_contains_only_observability_services():
    compose = load(ELASTIC_FILE)
    assert compose["name"] == "hirkanet-observability"
    assert set(compose["services"]) == {
        "elastic-certs-migrate",
        "elastic-certs-setup",
        "openssl-helper",
        "elasticsearch",
        "elastic-init",
        "logstash",
        "kibana",
        "docker-socket-proxy",
        "filebeat",
    }
    assert set(compose["networks"]) == {
        "logging-ingest",
        "elastic-backend",
        "docker-metadata",
        "elastic-access",
    }


def test_filebeat_depends_only_on_observability_services():
    filebeat = load(ELASTIC_FILE)["services"]["filebeat"]
    assert set(filebeat["depends_on"]) == {"logstash", "docker-socket-proxy"}


def test_elastic_images_use_official_registry_and_helpers_are_pinned():
    services = load(ELASTIC_FILE)["services"]

    for name in (
        "elastic-certs-migrate",
        "elastic-certs-setup",
        "elasticsearch",
        "elastic-init",
        "logstash",
        "kibana",
        "filebeat",
    ):
        assert services[name]["image"].startswith("docker.elastic.co/")

    assert services["filebeat"]["image"].startswith(
        "docker.elastic.co/beats/filebeat:"
    )
    assert services["docker-socket-proxy"]["image"].endswith(":v0.4.2")
    helper_dockerfile = (ROOT / "elk/openssl-helper/Dockerfile").read_text()
    assert "FROM alpine:3.21.3" in helper_dockerfile


def test_split_operations_are_documented():
    guide = (ROOT / "COMPOSE-DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "docker compose up -d --build" in guide
    assert "docker compose -f docker-compose.elastic.yml up -d --build" in guide
    assert "do not share a Docker network" in guide
