from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_application_json_is_parsed_and_ecs_fields_are_normalized():
    pipeline = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")

    assert 'source => "message"' in pipeline
    assert 'tag_on_failure => ["_hirkanet_json_parse_failure"]' in pipeline
    assert '"event_type" => "[event][type]"' in pipeline
    assert '"event_duration" => "[event][duration]"' in pipeline
    assert '"http_status_code" => "[http][response][status_code]"' in pipeline
    assert '"user_id" => "[user][id]"' in pipeline


def test_database_logs_are_classified_without_json_parsing():
    pipeline = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")

    assert '== "database"' in pipeline
    assert '"[service][name]" => "postgresql"' in pipeline
    assert '"[event][dataset]" => "postgresql.log"' in pipeline


def test_malformed_application_json_goes_only_to_dead_letter_output():
    pipeline = (ROOT / "elk/logstash/pipeline/logstash.conf").read_text(encoding="utf-8")

    conditional = 'if "_hirkanet_json_parse_failure" in [tags]'
    assert pipeline.count(conditional) >= 2
    assert '"[event][dataset]" => "hirkanet.dead_letter"' in pipeline
    assert '"[error][type]" => "json_parse_failure"' in pipeline


def test_filebeat_uses_restricted_socket_proxy_not_host_socket():
    compose = yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "elk/filebeat/filebeat.yml").read_text(encoding="utf-8"))

    assert config["processors"][0]["add_docker_metadata"]["host"] == (
        "tcp://docker-socket-proxy:2375"
    )
    filebeat_mounts = " ".join(compose["services"]["filebeat"]["volumes"])
    proxy_mounts = " ".join(compose["services"]["docker-socket-proxy"]["volumes"])
    assert "/var/run/docker.sock" not in filebeat_mounts
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy_mounts


def test_end_to_end_verification_script_checks_normal_and_dead_letter_paths():
    script = (ROOT / "elk/verify-ingestion.sh").read_text(encoding="utf-8")

    assert "hirkanet_log_role=application" in script
    assert "hirkanet-logs-*" in script
    assert "hirkanet-dead-letter-*" in script
    assert "valid_dead != 0" in script
    assert "invalid_normal != 0" in script
