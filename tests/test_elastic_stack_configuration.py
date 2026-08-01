from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    return yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8"))


def test_elasticsearch_tls_is_enabled_and_uses_split_certificates():
    service = load_compose()["services"]["elasticsearch"]
    env = service["environment"]

    assert env["xpack.security.http.ssl.enabled"] == "true"
    assert env["xpack.security.transport.ssl.enabled"] == "true"
    assert env["xpack.security.http.ssl.certificate_authorities"] == "certs/ca/ca.crt"
    assert env["xpack.security.http.ssl.key"] == "certs/elasticsearch/elasticsearch.key"
    assert "elastic_ca_private" not in " ".join(service["volumes"])


def test_kibana_and_elasticsearch_use_https():
    env = load_compose()["services"]["kibana"]["environment"]
    assert env["SERVER_SSL_ENABLED"] == "true"
    assert env["ELASTICSEARCH_HOSTS"] == '["https://elasticsearch:9200"]'


def test_filebeat_to_logstash_tls_is_enabled():
    config = yaml.safe_load((ROOT / "elk/filebeat/filebeat.yml").read_text(encoding="utf-8"))
    output = config["output.logstash"]

    assert output["ssl.enabled"] is True
    assert output["ssl.certificate_authorities"] == [
        "/usr/share/filebeat/certs/ca.crt"
    ]
    assert output["ssl.verification_mode"] == "full"


def test_logstash_uses_consistent_password_variable_tls_and_ilm_aliases():
    config = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")
    compose_command = load_compose()["services"]["logstash"]["command"][2]

    assert 'password => "${LOGSTASH_PASSWORD}"' in config
    assert "LOGSTASH_INTERNAL_PASSWORD" not in config
    assert 'export LOGSTASH_PASSWORD=' in compose_command
    assert 'hosts => ["https://elasticsearch:9200"]' in config
    assert config.count('ssl_verification_mode => "full"') == 2
    assert config.count("ilm_enabled => true") == 2
    assert 'ilm_rollover_alias => "hirkanet-logs"' in config
    assert 'ilm_policy => "hirkanet-logs-policy"' in config
    assert 'ilm_rollover_alias => "hirkanet-dead-letter"' in config
    assert 'ilm_policy => "hirkanet-dead-letter-policy"' in config
    assert 'index => "hirkanet-logs-%{+YYYY.MM.dd}"' not in config


def test_dead_letter_output_is_conditional_not_duplicate():
    config = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")

    assert 'if "_hirkanet_json_parse_failure" in [tags]' in config
    assert 'id => "hirkanet_dead_letter_output"' in config
    assert 'id => "hirkanet_normal_logs_output"' in config
    assert config.count('ilm_rollover_alias => "hirkanet-dead-letter"') == 1
    assert config.count('ilm_rollover_alias => "hirkanet-logs"') == 1


def test_ilm_setup_creates_policies_templates_and_write_aliases():
    script = (ROOT / "elk/setup-ilm.sh").read_text(encoding="utf-8")

    assert "/_ilm/policy/hirkanet-logs-policy" in script
    assert "/_index_template/hirkanet-logs-template" in script
    assert 'ensure_write_alias "hirkanet-logs" "hirkanet-logs-000001"' in script
    assert "/_ilm/policy/hirkanet-dead-letter-policy" in script
    assert "/_index_template/hirkanet-dead-letter-template" in script
    assert (
        'ensure_write_alias "hirkanet-dead-letter" "hirkanet-dead-letter-000001"'
        in script
    )


def test_elastic_stack_uses_official_pinned_version_family():
    compose = load_compose()
    services = compose["services"]

    assert services["elasticsearch"]["image"] == (
        "docker.elastic.co/elasticsearch/elasticsearch:${STACK_VERSION:-9.3.8}"
    )
    assert services["logstash"]["image"] == (
        "docker.elastic.co/logstash/logstash:${STACK_VERSION:-9.3.8}"
    )
    assert services["kibana"]["image"] == (
        "docker.elastic.co/kibana/kibana:${STACK_VERSION:-9.3.8}"
    )
    assert services["filebeat"]["image"] == (
        "docker.elastic.co/beats/filebeat:${STACK_VERSION:-9.3.8}"
    )
    assert services["docker-socket-proxy"]["image"].endswith(":v0.4.2")
    assert "latest" not in (ROOT / "docker-compose.elastic.yml").read_text()


def test_elastic_init_uses_shell_safe_json_payloads():
    command = load_compose()["services"]["elastic-init"]["command"][2]
    assert '--data "{\\"password\\":\\"$${KIBANA_PASSWORD}\\"}"' in command
    assert (
        '--data "{\\"password\\":\\"$${LOGSTASH_PASSWORD}\\",'
        '\\"roles\\":[\\"logstash_writer\\"],'
        '\\"full_name\\":\\"Hirkanet Logstash Writer\\"}"'
        in command
    )
