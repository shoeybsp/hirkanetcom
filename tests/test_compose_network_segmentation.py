from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "docker-compose.yml"
ELASTIC_FILE = ROOT / "docker-compose.elastic.yml"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def service_networks(service):
    networks = service.get("networks", [])
    return set(networks if not isinstance(networks, dict) else networks.keys())


def test_application_database_network_is_private_and_frontend_is_separate():
    compose = load(APP_FILE)

    assert set(compose["networks"]) == {"app-db", "frontend"}
    assert compose["networks"]["app-db"]["internal"] is True
    assert "internal" not in compose["networks"]["frontend"]
    assert service_networks(compose["services"]["db"]) == {"app-db"}
    assert service_networks(compose["services"]["migrate"]) == {"app-db"}
    assert service_networks(compose["services"]["app"]) == {"app-db", "frontend"}


def test_elastic_private_networks_and_loopback_access_network_are_separated():
    compose = load(ELASTIC_FILE)

    assert set(compose["networks"]) == {
        "logging-ingest",
        "elastic-backend",
        "docker-metadata",
        "elastic-access",
    }
    for name in ("logging-ingest", "elastic-backend", "docker-metadata"):
        assert compose["networks"][name]["internal"] is True
    assert "internal" not in compose["networks"]["elastic-access"]

    expected = {
        "elasticsearch": {"elastic-backend", "elastic-access"},
        "elastic-init": {"elastic-backend"},
        "logstash": {"logging-ingest", "elastic-backend"},
        "kibana": {"elastic-backend", "elastic-access"},
        "docker-socket-proxy": {"docker-metadata"},
        "filebeat": {"logging-ingest", "docker-metadata"},
    }
    for name, networks in expected.items():
        assert service_networks(compose["services"][name]) == networks

    assert compose["services"]["elasticsearch"]["ports"] == ["127.0.0.1:9200:9200"]
    assert compose["services"]["kibana"]["ports"] == ["127.0.0.1:5601:5601"]


def test_certificate_jobs_have_no_network_access():
    compose = load(ELASTIC_FILE)

    for service_name in ("elastic-certs-migrate", "elastic-certs-setup", "openssl-helper"):
        service = compose["services"][service_name]
        assert service.get("network_mode") == "none"
        assert "networks" not in service


def test_compose_projects_have_no_shared_network():
    app = set(load(APP_FILE)["networks"])
    elastic = set(load(ELASTIC_FILE)["networks"])
    assert app.isdisjoint(elastic)
