from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _app_config():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return compose["services"]["app"]


def test_application_container_has_runtime_hardening():
    app = _app_config()
    assert app["init"] is True
    assert app["read_only"] is True
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["cap_drop"] == ["ALL"]
    assert app["pids_limit"] == 256
    assert app["stop_grace_period"] == "30s"


def test_application_tmp_is_small_and_hardened():
    tmpfs = _app_config()["tmpfs"]
    assert any(
        entry.startswith("/tmp:")
        and "size=64m" in entry
        and "mode=1777" in entry
        and "noexec" in entry
        and "nosuid" in entry
        and "nodev" in entry
        for entry in tmpfs
    )


def test_only_declared_runtime_paths_are_writable():
    volumes = _app_config()["volumes"]
    # data is a Docker-managed named volume (not a host bind mount) since
    # the switch documented in docs/depoly-readme.md and architecture.md
    # section 7 - its ownership comes from the image, not the host.
    assert "hirkanet_data:/app/data" in volumes
    assert "./uploads:/app/uploads" in volumes
    assert "./static/uploads:/app/static/uploads" in volumes
    assert not any(volume.endswith(":/app") for volume in volumes)
