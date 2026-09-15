#!/usr/bin/env python3
"""Hirkanet storage capacity, freshness, and retention-policy monitor.

Device-aware: iterates over data/devices/*/snapshots as well as the legacy
single-device data/snapshots layout, and reports per-device metrics for
storage usage, snapshot count, stale staging directories, and active
snapshot pointer integrity.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise SystemExit(f"ERROR: {name} must not be negative")
    return value


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except FileNotFoundError:
            continue
    return total


def percent(used: int, total: int) -> float:
    return round((used / total * 100.0), 2) if total else 0.0


def severity(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "ok"


def max_status(statuses: List[str]) -> str:
    rank = {"ok": 0, "warning": 1, "critical": 2, "unknown": 1}
    return max(statuses, key=lambda item: rank.get(item, 1), default="ok")


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class Check:
    name: str
    status: str
    value: Any
    unit: str = ""
    message: str = ""


def compose_exec(compose_file: str, args: List[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", compose_file, "exec", "-T", "db", *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def postgres_checks(compose_file: str) -> List[Check]:
    checks: List[Check] = []
    if shutil.which("docker") is None:
        return [Check("postgres_database_size", "unknown", None, message="docker command is unavailable")]

    sql = "SELECT pg_database_size(current_database());"
    result = compose_exec(
        compose_file,
        ["sh", "-ec", "export PGPASSWORD=\"$(cat /run/secrets/postgres_password)\"; psql --host=127.0.0.1 --username=\"$POSTGRES_USER\" --dbname=\"$POSTGRES_DB\" --no-password --tuples-only --no-align --command=\"$1\"", "sh", sql],
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[-500:]
        return [Check("postgres_database_size", "unknown", None, message=message or "database query failed")]
    try:
        db_bytes = int(result.stdout.strip())
    except ValueError:
        return [Check("postgres_database_size", "unknown", result.stdout.strip(), message="unexpected query output")]
    warn = env_int("POSTGRES_DB_WARN_BYTES", 5 * 1024**3)
    crit = env_int("POSTGRES_DB_CRITICAL_BYTES", 10 * 1024**3)
    checks.append(Check("postgres_database_size", severity(db_bytes, warn, crit), db_bytes, "bytes"))

    result = compose_exec(compose_file, ["df", "-Pk", "/var/lib/postgresql/data"])
    if result.returncode == 0:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        try:
            fields = lines[-1].split()
            used_pct = float(fields[4].rstrip("%"))
            warn_pct = env_int("POSTGRES_VOLUME_WARN_PERCENT", 80)
            crit_pct = env_int("POSTGRES_VOLUME_CRITICAL_PERCENT", 90)
            checks.append(Check("postgres_volume_used", severity(used_pct, warn_pct, crit_pct), used_pct, "percent"))
        except (IndexError, ValueError):
            checks.append(Check("postgres_volume_used", "unknown", None, message="unexpected df output"))
    else:
        checks.append(Check("postgres_volume_used", "unknown", None, message=(result.stderr or result.stdout).strip()[-500:]))
    return checks


def backup_checks(backup_dir: Path) -> List[Check]:
    checks: List[Check] = []
    total = dir_size(backup_dir)
    warn_bytes = env_int("BACKUP_STORAGE_WARN_BYTES", 20 * 1024**3)
    crit_bytes = env_int("BACKUP_STORAGE_CRITICAL_BYTES", 40 * 1024**3)
    checks.append(Check("postgres_backup_storage", severity(total, warn_bytes, crit_bytes), total, "bytes"))

    verified: List[tuple[datetime, Path]] = []
    if backup_dir.exists():
        for meta in backup_dir.glob("*.dump.meta"):
            values: dict[str, str] = {}
            try:
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        values[key] = value
            except OSError:
                continue
            if values.get("restore_test") != "passed":
                continue
            created = parse_timestamp(values.get("created_at_utc", ""))
            if created:
                verified.append((created, meta))
    if not verified:
        checks.append(Check("latest_verified_backup_age", "critical", None, message="no restore-tested PostgreSQL backup found"))
    else:
        latest, meta = max(verified, key=lambda item: item[0])
        age_hours = (datetime.now(timezone.utc) - latest.astimezone(timezone.utc)).total_seconds() / 3600
        warn_hours = env_int("BACKUP_MAX_AGE_HOURS", 26)
        crit_hours = env_int("BACKUP_CRITICAL_AGE_HOURS", 48)
        checks.append(Check("latest_verified_backup_age", severity(age_hours, warn_hours, crit_hours), round(age_hours, 2), "hours", meta.name))
    return checks


def _active_snapshot_check(name: str, data_dir: Path, snapshots_dir: Path) -> Check:
    """Check whether data_dir/current.json points at a snapshot that actually
    exists under snapshots_dir. Shared by the legacy and per-device paths so
    every device - not just the legacy one - gets this integrity check."""
    pointer = data_dir / "current.json"
    if not pointer.exists():
        return Check(name, "critical", None, message=f"{data_dir}/current.json is missing")
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Check(name, "critical", None, message=str(exc))
    snapshot_id = payload.get("snapshot_id")
    target = snapshots_dir / str(snapshot_id) if snapshot_id else None
    if snapshot_id and target and target.is_dir():
        return Check(name, "ok", snapshot_id)
    return Check(name, "critical", snapshot_id, message="active snapshot directory missing")


def snapshot_checks(root: Path, per_device: bool) -> List[Check]:
    # per_device is accepted for CLI compatibility with storage-retention.py's
    # flag of the same name, but monitoring always reports every layout that
    # actually exists on disk - unlike retention, hiding data behind an
    # unset flag has no safety benefit here, only blind spots.
    del per_device
    checks: List[Check] = []
    data_root = root / "data"

    # Legacy single-device layout (fallback / the auto-registered default
    # device from before multi-device support existed).
    legacy_snapshots = data_root / "snapshots"
    if legacy_snapshots.exists():
        total = dir_size(legacy_snapshots)
        warn = env_int("FORTIGATE_STORAGE_WARN_BYTES", 5 * 1024**3)
        crit = env_int("FORTIGATE_STORAGE_CRITICAL_BYTES", 10 * 1024**3)
        checks.append(Check("fortigate_snapshot_storage_legacy", severity(total, warn, crit), total, "bytes"))
        completed = [p for p in legacy_snapshots.iterdir() if p.is_dir() and not p.name.startswith(".")]
        keep = env_int("FORTIGATE_KEEP_SNAPSHOTS", 10)
        excess = max(0, len(completed) - keep)
        checks.append(Check("fortigate_snapshot_count_legacy", "warning" if excess else "ok", len(completed), "snapshots", f"retention target={keep}"))
        checks.append(_active_snapshot_check("fortigate_active_snapshot_legacy", data_root, legacy_snapshots))

    # Device-aware layout: data/devices/<device_id>/snapshots
    devices_dir = data_root / "devices"
    if devices_dir.is_dir():
        for device_path in sorted(devices_dir.iterdir()):
            if not device_path.is_dir():
                continue
            device_name = device_path.name
            snapshots_dir = device_path / "snapshots"
            total = dir_size(snapshots_dir)
            warn = env_int("FORTIGATE_STORAGE_WARN_BYTES", 5 * 1024**3)
            crit = env_int("FORTIGATE_STORAGE_CRITICAL_BYTES", 10 * 1024**3)
            checks.append(Check(f"fortigate_snapshot_storage_{device_name}", severity(total, warn, crit), total, "bytes"))
            completed = [p for p in snapshots_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
            keep = env_int("FORTIGATE_KEEP_SNAPSHOTS", 10)
            excess = max(0, len(completed) - keep)
            checks.append(Check(f"fortigate_snapshot_count_{device_name}", "warning" if excess else "ok", len(completed), "snapshots", f"retention target={keep}"))
            staging = [p for p in snapshots_dir.glob(".staging-*") if p.is_dir()]
            stale_hours = env_int("FORTIGATE_STAGING_MAX_AGE_HOURS", 24)
            now = datetime.now(timezone.utc).timestamp()
            stale = [p for p in staging if (now - p.stat().st_mtime) / 3600 > stale_hours]
            checks.append(Check(f"stale_fortigate_staging_{device_name}", "warning" if stale else "ok", len(stale), "directories", f"older than {stale_hours}h"))
            # Each device has its own current.json under its own data_dir -
            # unlike the old single-pointer layout, there is no single
            # shared "active snapshot" to check once at the top level.
            checks.append(_active_snapshot_check(f"fortigate_active_snapshot_{device_name}", device_path, snapshots_dir))

    if not legacy_snapshots.exists() and not (devices_dir.is_dir() and any(devices_dir.iterdir())):
        checks.append(Check("fortigate_active_snapshot", "critical", None, message="no device data found under data/ or data/devices/"))

    return checks


def local_storage_checks(root: Path) -> List[Check]:
    usage = shutil.disk_usage(root)
    used_pct = percent(usage.used, usage.total)
    warn_pct = env_int("HOST_STORAGE_WARN_PERCENT", 80)
    crit_pct = env_int("HOST_STORAGE_CRITICAL_PERCENT", 90)
    checks = [Check("host_filesystem_used", severity(used_pct, warn_pct, crit_pct), used_pct, "percent")]
    upload_bytes = dir_size(root / "static" / "uploads") + dir_size(root / "uploads")
    warn_uploads = env_int("UPLOAD_STORAGE_WARN_BYTES", 5 * 1024**3)
    crit_uploads = env_int("UPLOAD_STORAGE_CRITICAL_BYTES", 10 * 1024**3)
    checks.append(Check("upload_storage", severity(upload_bytes, warn_uploads, crit_uploads), upload_bytes, "bytes", "uploads are never automatically deleted"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--compose-file", default=os.getenv("COMPOSE_FILE", "docker-compose.yml"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--per-device",
        action="store_true",
        help="accepted for compatibility with storage-retention.py; monitoring always reports every device regardless",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    checks: List[Check] = []
    checks.extend(local_storage_checks(root))
    checks.extend(backup_checks(root / "backups" / "postgres"))
    checks.extend(snapshot_checks(root, per_device=args.per_device))
    checks.extend(postgres_checks(str((root / args.compose_file).resolve())))

    overall = max_status([c.status for c in checks])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "checks": [asdict(c) for c in checks],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Hirkanet storage status: {overall.upper()}")
        for check in checks:
            value = "unknown" if check.value is None else f"{check.value}{(' ' + check.unit) if check.unit else ''}"
            suffix = f" - {check.message}" if check.message else ""
            print(f"[{check.status.upper():8}] {check.name}: {value}{suffix}")
    return {"ok": 0, "warning": 1, "unknown": 1, "critical": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
