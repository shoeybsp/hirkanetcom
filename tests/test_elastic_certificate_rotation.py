from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose():
    return yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text(encoding="utf-8"))


def test_setup_does_not_delete_or_recreate_existing_ca_silently():
    script = (ROOT / "elk/setup-certs.sh").read_text(encoding="utf-8")

    assert "Refusing to replace the trust root automatically" in script
    assert "ca_crt_exists != ca_key_exists" in script
    assert "exit 1" in script
    assert 'rm -rf "${CA_PRIVATE_DIR}"' not in script


def test_ca_key_is_retained_protected_and_not_runtime_mounted():
    compose = load_compose()
    script = (ROOT / "elk/setup-certs.sh").read_text(encoding="utf-8")

    assert 'chmod 0600 "${ca_key}"' in script
    assert 'rm -f "${ca_key}"' not in script

    for service_name in ("elasticsearch", "elastic-init", "logstash", "kibana", "filebeat"):
        mounts = " ".join(compose["services"][service_name].get("volumes", []))
        assert "elastic_ca_private" not in mounts


def test_missing_service_certificates_use_existing_ca():
    script = (ROOT / "elk/setup-certs.sh").read_text(encoding="utf-8")

    assert '--ca-cert "${ca_crt}"' in script
    assert '--ca-key "${ca_key}"' in script
    assert "reissuing them with the existing CA" in script


def test_legacy_certificates_are_migrated_without_ca_rotation():
    compose = load_compose()
    script = (ROOT / "elk/migrate-legacy-certs.sh").read_text(encoding="utf-8")

    assert "legacy_elastic_certs" in compose["volumes"]
    assert "Migrating the existing Elastic trust root" in script
    assert "without changing the CA" in script
    assert "Refusing to migrate or replace the trust root automatically" in script


def test_logstash_pkcs8_conversion_is_ordered_after_certificate_setup():
    compose = load_compose()
    helper = compose["services"]["openssl-helper"]

    assert helper["depends_on"]["elastic-certs-setup"]["condition"] == (
        "service_completed_successfully"
    )
    assert helper["build"]["dockerfile"] == "elk/openssl-helper/Dockerfile"
    assert "apk add" not in " ".join(helper.get("command", []))


def test_rotation_script_removes_containers_before_certificate_volumes():
    script = (ROOT / "elk/rotate-elastic-ca.sh").read_text(encoding="utf-8")

    assert "--confirm-trust-root-rotation" in script
    assert '"${compose[@]}" down --remove-orphans' in script
    assert "docker volume rm" in script
    assert script.index('"${compose[@]}" down --remove-orphans') < script.index(
        "docker volume rm"
    )
    assert "old-ca.sha256" in script
    assert "hirkanet-elastic-ca.sha256" in script


def test_documentation_distinguishes_cert_renewal_from_ca_rotation():
    docs = (ROOT / "ELK-SETUP.md").read_text(encoding="utf-8")
    assert "Service-certificate renewal without CA rotation" in docs
    assert "Explicit trust-root rotation" in docs
    assert "never silently replaces" in docs
