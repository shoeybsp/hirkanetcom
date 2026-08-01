from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    app = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    elastic = yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text())
    return {"services": {**app["services"], **elastic["services"]}}


def test_secret_values_are_not_compose_environment_substitutions():
    text = (ROOT / "docker-compose.yml").read_text() + (ROOT / "docker-compose.elastic.yml").read_text()
    forbidden = [
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}",
        "ELASTIC_PASSWORD: ${ELASTIC_PASSWORD}",
        "KIBANA_PASSWORD: ${KIBANA_PASSWORD}",
        "LOGSTASH_PASSWORD: ${LOGSTASH_PASSWORD}",
        "XPACK_SECURITY_ENCRYPTIONKEY: ${KIBANA_SECURITY_ENCRYPTION_KEY}",
    ]
    for value in forbidden:
        assert value not in text


def test_services_mount_expected_secrets():
    services = load_compose()["services"]
    assert "postgres_password" in services["db"]["secrets"]
    assert {"postgres_password", "flask_secret_key", "bootstrap_admin_password"}.issubset(
        services["app"]["secrets"]
    )
    assert "elastic_password" in services["elasticsearch"]["secrets"]
    assert {"elastic_password", "kibana_password", "logstash_password"}.issubset(
        services["elastic-init"]["secrets"]
    )


def test_application_supports_file_based_secrets():
    import re

    app = (ROOT / "api/app.py").read_text()
    models = (ROOT / "models.py").read_text()
    assert re.search(r'read_secret\(\s*"SECRET_KEY"', app)
    assert re.search(r'read_secret\(\s*"POSTGRES_PASSWORD"', models)
    assert re.search(r'read_secret\(\s*"BOOTSTRAP_ADMIN_PASSWORD"', models)
    assert "URL.create(" in models


def test_real_secret_files_are_ignored():
    ignore = (ROOT / ".gitignore").read_text()
    assert "secrets/*" in ignore
    assert "!secrets/*.example" in ignore
