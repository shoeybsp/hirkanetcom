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


def test_application_network_is_private_and_isolated():
    compose = load(APP_FILE)
    assert set(compose["networks"]) == {"app-db"}
    assert compose["networks"]["app-db"]["internal"] is True
    assert service_networks(compose["services"]["app"]) == {"app-db"}
    assert service_networks(compose["services"]["db"]) == {"app-db"}


def test_elastic_networks_are_private_and_isolated():
    compose = load(ELASTIC_FILE)
    assert set(compose["networks"]) == {"logging-ingest", "elastic-backend"}
    assert all(v["internal"] is True for v in compose["networks"].values())
    expected = {
        "elasticsearch": {"elastic-backend"},
        "elastic-init": {"elastic-backend"},
        "logstash": {"logging-ingest", "elastic-backend"},
        "kibana": {"elastic-backend"},
        "filebeat": {"logging-ingest"},
    }
    for name, networks in expected.items():
        assert service_networks(compose["services"][name]) == networks


def test_certificate_setup_has_no_network_access():
    service = load(ELASTIC_FILE)["services"]["elastic-certs-setup"]
    assert service.get("network_mode") == "none"
    assert "networks" not in service


def test_compose_projects_have_no_shared_network():
    app = set(load(APP_FILE)["networks"])
    elastic = set(load(ELASTIC_FILE)["networks"])
    assert app.isdisjoint(elastic)
