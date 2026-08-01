from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_compose_has_no_fixed_container_names():
    services = load_compose()["services"]
    assert all("container_name" not in service for service in services.values())


def test_log_sources_use_stable_role_labels():
    services = load_compose()["services"]
    assert services["app"]["labels"]["hirkanet_log_role"] == "application"
    assert services["db"]["labels"]["hirkanet_log_role"] == "database"


def test_filebeat_filters_by_role_label():
    config = (ROOT / "elk/filebeat/filebeat.yml").read_text()
    assert "container.labels.hirkanet_log_role: application" in config
    assert "container.labels.hirkanet_log_role: database" in config
    assert "container.name:" not in config


def test_logstash_parses_application_logs_by_role_label():
    config = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text()
    assert '[container][labels][hirkanet_log_role] == "application"' in config
    assert '[container][name]' not in config
