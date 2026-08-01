from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def setup_command() -> str:
    compose = yaml.safe_load((ROOT / "docker-compose.elastic.yml").read_text())
    command = compose["services"]["elastic-certs-setup"]["command"]
    return command[-1]


def test_setup_does_not_delete_or_recreate_existing_ca_silently():
    command = setup_command()
    assert "rm -rf ca" not in command
    assert "Refusing to replace the trust root automatically" in command
    assert "exit 1" in command


def test_ca_key_is_retained_and_protected():
    command = setup_command()
    assert "rm -f ca/ca.key" not in command
    assert "chmod 600 ca/ca.key" in command


def test_missing_service_certificates_use_existing_ca():
    command = setup_command()
    assert "--ca-cert ca/ca.crt" in command
    assert "--ca-key ca/ca.key" in command
    assert "reissuing them with the existing CA" in command


def test_rotation_script_requires_explicit_confirmation():
    script = (ROOT / "elk" / "rotate-elastic-ca.sh").read_text()
    assert "--confirm-trust-root-rotation" in script
    assert "docker volume rm" in script
    assert "old-ca.sha256" in script
    assert "hirkanet-elastic-ca.sha256" in script


def test_documentation_distinguishes_cert_renewal_from_ca_rotation():
    docs = (ROOT / "ELK-SETUP.md").read_text()
    assert "Service-certificate renewal without CA rotation" in docs
    assert "Explicit trust-root rotation" in docs
    assert "never silently replaces" in docs
