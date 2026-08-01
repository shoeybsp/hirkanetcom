from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_storage_scripts_exist_and_are_executable():
    for name in ("storage-monitor.py", "storage-retention.py"):
        path = ROOT / "scripts" / name
        assert path.exists()
        assert path.stat().st_mode & 0o111


def test_storage_scripts_help_runs():
    for name in ("storage-monitor.py", "storage-retention.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_retention_defaults_to_dry_run_and_protects_uploads():
    text = (ROOT / "scripts" / "storage-retention.py").read_text()
    assert "dry_run = not args.apply" in text
    assert "Uploads were not modified" in text
    assert "protected.add(active)" in text


def test_monitor_checks_required_storage_domains():
    text = (ROOT / "scripts" / "storage-monitor.py").read_text()
    for marker in (
        "postgres_database_size",
        "postgres_volume_used",
        "latest_verified_backup_age",
        "fortigate_snapshot_storage",
        "fortigate_active_snapshot",
        "upload_storage",
        "host_filesystem_used",
    ):
        assert marker in text


def test_storage_policy_documented_and_thresholds_configurable():
    document = (ROOT / "STORAGE-MONITORING.md").read_text()
    env_example = (ROOT / ".env.example").read_text()
    assert "never deleted automatically" in document
    assert "restore_test=passed" in document
    for name in (
        "HOST_STORAGE_WARN_PERCENT",
        "POSTGRES_DB_WARN_BYTES",
        "BACKUP_MAX_AGE_HOURS",
        "FORTIGATE_KEEP_SNAPSHOTS",
        "RETENTION_DAYS",
        "KEEP_MINIMUM",
    ):
        assert name in env_example
