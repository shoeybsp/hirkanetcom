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
    assert set(compose["services"]) == {"app", "db", "migrate"}
    assert set(compose["networks"]) == {"app-db"}


def test_elastic_compose_contains_only_observability_services():
    compose = load(ELASTIC_FILE)
    assert compose["name"] == "hirkanet-observability"
    assert set(compose["services"]) == {
        "elastic-certs-setup", "elasticsearch", "elastic-init",
        "logstash", "kibana", "filebeat"
    }
    assert set(compose["networks"]) == {"logging-ingest", "elastic-backend"}


def test_filebeat_has_no_cross_project_dependency():
    filebeat = load(ELASTIC_FILE)["services"]["filebeat"]
    assert "depends_on" not in filebeat


def test_elastic_images_use_official_registry():
    services = load(ELASTIC_FILE)["services"]
    for service in services.values():
        assert service["image"].startswith("docker.elastic.co/")
    assert services["filebeat"]["image"].startswith("docker.elastic.co/beats/filebeat:")


def test_split_operations_are_documented():
    guide = (ROOT / "COMPOSE-DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "docker compose up -d --build" in guide
    assert "docker compose -f docker-compose.elastic.yml up -d" in guide
    assert "do not share a Docker network" in guide
