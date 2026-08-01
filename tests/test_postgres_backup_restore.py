from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backup_restore_scripts_exist_and_are_executable():
    for name in ("postgres-backup.sh", "postgres-restore-test.sh", "postgres-restore.sh"):
        path = ROOT / "scripts" / name
        assert path.exists()
        assert path.stat().st_mode & 0o111


def test_backup_uses_custom_format_checksum_and_restore_test():
    text = (ROOT / "scripts" / "postgres-backup.sh").read_text()
    assert "--format=custom" in text
    assert "sha256sum" in text
    assert "postgres-restore-test.sh" in text
    assert "restore_test=passed" in text
    assert "POSTGRES_PASSWORD" not in text or "POSTGRES_PASSWORD_FILE" not in text
    assert "/run/secrets/postgres_password" in text


def test_restore_test_is_disposable_and_checks_schema():
    text = (ROOT / "scripts" / "postgres-restore-test.sh").read_text()
    assert "createdb" in text
    assert "dropdb" in text
    assert "alembic_version" in text
    assert "--exit-on-error" in text


def test_production_restore_requires_explicit_override():
    text = (ROOT / "scripts" / "postgres-restore.sh").read_text()
    assert "--allow-production-target" in text
    assert "refusing to restore over production" in text
    assert "--confirm-restore" in text


def test_backups_are_gitignored_and_documented():
    ignore = (ROOT / ".gitignore").read_text()
    assert "backups/" in ignore
    assert (ROOT / "POSTGRES-BACKUP-RESTORE.md").exists()
