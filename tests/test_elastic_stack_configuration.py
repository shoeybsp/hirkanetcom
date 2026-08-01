from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    return yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text())


def test_elasticsearch_tls_is_enabled():
    env = load_compose()["services"]["elasticsearch"]["environment"]
    assert env["xpack.security.http.ssl.enabled"] == "true"
    assert env["xpack.security.transport.ssl.enabled"] == "true"
    assert env["xpack.security.http.ssl.certificate_authorities"] == "certs/ca/ca.crt"


def test_kibana_and_elasticsearch_use_https():
    env = load_compose()["services"]["kibana"]["environment"]
    assert env["SERVER_SSL_ENABLED"] == "true"
    assert env["ELASTICSEARCH_HOSTS"] == '["https://elasticsearch:9200"]'


def test_filebeat_to_logstash_tls_is_enabled():
    config = yaml.safe_load((ROOT / "elk/filebeat/filebeat.yml").read_text())
    output = config["output.logstash"]
    assert output["ssl.enabled"] is True
    assert output["ssl.certificate_authorities"] == [
        "/usr/share/filebeat/certs/ca/ca.crt"
    ]


def test_logstash_uses_tls_and_ilm_alias():
    config = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text()
    assert 'hosts => ["https://elasticsearch:9200"]' in config
    assert 'ssl_enabled => true' in config
    assert 'ilm_enabled => true' in config
    assert 'ilm_rollover_alias => "hirkanet-logs"' in config
    assert 'ilm_policy => "hirkanet-logs-policy"' in config
    assert 'ilm_rollover_alias => "hirkanet-dead-letter"' in config
    assert 'ilm_policy => "hirkanet-dead-letter-policy"' in config
    assert 'index => "hirkanet-dead-letter-%{+YYYY.MM.dd}"' not in config


def test_ilm_setup_creates_policy_template_and_alias():
    script = (ROOT / "elk/setup-ilm.sh").read_text()
    assert "/_ilm/policy/hirkanet-logs-policy" in script
    assert "/_index_template/hirkanet-logs-template" in script
    assert "/hirkanet-logs-000001" in script
    assert '"hirkanet-logs":{"is_write_index":true}' in script
    assert "/_ilm/policy/hirkanet-dead-letter-policy" in script
    assert "/_index_template/hirkanet-dead-letter-template" in script
    assert "/hirkanet-dead-letter-000001" in script
    assert '"hirkanet-dead-letter":{"is_write_index":true}' in script


def test_elastic_stack_uses_one_version_variable():
    compose = (ROOT / "docker-compose.elastic.yml").read_text()
    assert "FILEBEAT_VERSION" not in compose
    assert "docker.elastic.co/beats/filebeat:${STACK_VERSION:-9.3.8}" in compose


def test_elastic_init_uses_shell_safe_json_payloads():
    command = load_compose()["services"]["elastic-init"]["command"][2]
    assert '--data "{\\"password\\":\\"$${KIBANA_PASSWORD}\\"}"' in command
    assert (
        '--data "{\\"password\\":\\"$${LOGSTASH_PASSWORD}\\",'
        '\\"roles\\":[\\"logstash_writer\\"],'
        '\\"full_name\\":\\"Hirkanet Logstash Writer\\"}"'
        in command
    )
    assert '--data "{"password"' not in command
