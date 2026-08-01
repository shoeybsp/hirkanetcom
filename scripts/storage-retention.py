#!/usr/bin/env python3
"""Apply Hirkanet storage-retention policies to safe, non-live artifacts."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

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


def remove(path: Path, dry_run: bool) -> None:
    print(f"{'WOULD REMOVE' if dry_run else 'REMOVING'} {path}")
    if dry_run:
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def prune_backup_sets(root: Path, dry_run: bool) -> None:
    backup_dir = root / "backups" / "postgres"
    retention_days = env_int("RETENTION_DAYS", 14)
    keep_minimum = env_int("KEEP_MINIMUM", 7)
    now = time.time()
    dumps = sorted(backup_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True) if backup_dir.exists() else []
    for dump in dumps[keep_minimum:]:
        if (now - dump.stat().st_mtime) < retention_days * 86400:
            continue
        for path in (dump, Path(str(dump) + ".sha256"), Path(str(dump) + ".meta")):
            if path.exists():
                remove(path, dry_run)

    partial_age = env_int("BACKUP_PARTIAL_MAX_AGE_HOURS", 24) * 3600
    for pattern in ("*.partial", "*.tmp"):
        for path in backup_dir.glob(pattern) if backup_dir.exists() else []:
            if now - path.stat().st_mtime > partial_age:
                remove(path, dry_run)


def active_snapshot_id(data_dir: Path) -> str | None:
    pointer = data_dir / "current.json"
    if not pointer.exists():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8")).get("snapshot_id")
        return str(value) if value else None
    except (OSError, json.JSONDecodeError):
        return None


def prune_snapshots(root: Path, dry_run: bool) -> None:
    data_dir = root / "data"
    snapshots_dir = data_dir / "snapshots"
    if not snapshots_dir.exists():
        return
    active = active_snapshot_id(data_dir)
    keep = max(1, env_int("FORTIGATE_KEEP_SNAPSHOTS", 10))
    completed = sorted(
        [p for p in snapshots_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    protected = {p.name for p in completed[:keep]}
    if active:
        protected.add(active)
    for path in completed:
        if path.name not in protected:
            remove(path, dry_run)

    stale_seconds = env_int("FORTIGATE_STAGING_MAX_AGE_HOURS", 24) * 3600
    now = time.time()
    for path in snapshots_dir.glob(".staging-*"):
        if path.is_dir() and now - path.stat().st_mtime > stale_seconds:
            remove(path, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform deletion; default is dry-run")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    dry_run = not args.apply
    print("Storage retention mode:", "DRY RUN" if dry_run else "APPLY")
    prune_backup_sets(root, dry_run)
    prune_snapshots(root, dry_run)
    print("Uploads were not modified; media deletion requires application-aware review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
