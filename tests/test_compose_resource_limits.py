from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP_COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
ELASTIC_COMPOSE = yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8"))
COMPOSE = {"services": {**APP_COMPOSE["services"], **ELASTIC_COMPOSE["services"]}}


def test_every_service_has_cpu_and_memory_limits():
    for name, service in COMPOSE["services"].items():
        assert "cpus" in service, f"{name} must define a CPU limit"
        assert "mem_limit" in service, f"{name} must define a memory limit"
        assert "mem_reservation" in service, f"{name} must define a memory reservation"


def test_every_service_has_pid_limit():
    for name, service in COMPOSE["services"].items():
        assert "pids_limit" in service, f"{name} must define a PID limit"
        assert int(service["pids_limit"]) > 0


def test_elasticsearch_memory_limit_exceeds_heap():
    service = COMPOSE["services"]["elasticsearch"]
    assert service["mem_limit"] == "1536m"
    assert service["mem_reservation"] == "1g"


def test_logstash_memory_limit_exceeds_heap():
    service = COMPOSE["services"]["logstash"]
    assert service["mem_limit"] == "768m"
    assert service["mem_reservation"] == "512m"
