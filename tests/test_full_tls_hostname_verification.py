from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    return yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8"))


def test_filebeat_requires_full_hostname_verification():
    text = (ROOT / "elk/filebeat/filebeat.yml").read_text(encoding="utf-8")
    assert "ssl.verification_mode: full" in text
    assert "ssl.verification_mode: certificate" not in text
    assert 'hosts: ["logstash:5044"]' in text


def test_logstash_elasticsearch_outputs_require_full_verification():
    text = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")
    assert text.count('ssl_verification_mode => "full"') == 2
    assert 'hosts => ["https://elasticsearch:9200"]' in text
    assert 'ssl_verification_mode => "none"' not in text


def test_kibana_and_transport_use_full_verification():
    compose = load_compose()
    es_env = compose["services"]["elasticsearch"]["environment"]
    kibana_env = compose["services"]["kibana"]["environment"]
    assert es_env["xpack.security.transport.ssl.verification_mode"] == "full"
    assert kibana_env["ELASTICSEARCH_SSL_VERIFICATIONMODE"] == "full"
    assert kibana_env["ELASTICSEARCH_HOSTS"] == '["https://elasticsearch:9200"]'


def test_certificates_cover_runtime_service_names_and_local_health_hosts():
    compose_text = (ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8")
    assert "dns: [elasticsearch, localhost]" in compose_text
    assert "dns: [kibana, localhost]" in compose_text
    assert "dns: [logstash, localhost]" in compose_text
    assert compose_text.count("ip: [127.0.0.1]") >= 3
