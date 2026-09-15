#!/usr/bin/env python3
"""Apply Hirkanet storage-retention policies to safe, non-live artifacts.

Device-aware: prunes old snapshots under both the legacy data/snapshots
layout and every data/devices/<device_id>/snapshots directory, always -
not gated behind a flag an operator has to remember to pass, since a
missed flag here silently means unbounded snapshot growth for every
non-legacy device rather than a visible failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import List

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
    dumps = (
        sorted(backup_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
        if backup_dir.exists()
        else []
    )
    for dump in dumps[keep_minimum:]:
        if (now - dump.stat().st_mtime) < retention_days * 86400:
            continue
        for suffix in ("", ".sha256", ".meta"):
            p = Path(str(dump) + suffix)
            if p.exists():
                remove(p, dry_run)

    partial_age = env_int("BACKUP_PARTIAL_MAX_AGE_HOURS", 24) * 3600
    for pattern in ("*.partial", "*.tmp"):
        for p in backup_dir.glob(pattern) if backup_dir.exists() else []:
            if now - p.stat().st_mtime > partial_age:
                remove(p, dry_run)


def active_snapshot_id(data_dir: Path) -> str | None:
    pointer = data_dir / "current.json"
    if not pointer.exists():
        return None
    try:
        return str(json.loads(pointer.read_text(encoding="utf-8")).get("snapshot_id"))
    except (OSError, json.JSONDecodeError):
        return None


def _prune_one_snapshot_dir(data_dir: Path, snapshots_dir: Path, dry_run: bool) -> None:
    """Prune completed snapshots beyond the keep threshold and stale staging
    directories under a single device's (or the legacy) snapshots_dir. The
    currently active snapshot is always protected, even if it happens to be
    older than other retained snapshots."""
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
    for p in completed:
        if p.name not in protected:
            remove(p, dry_run)

    stale_seconds = env_int("FORTIGATE_STAGING_MAX_AGE_HOURS", 24) * 3600
    now = time.time()
    for p in snapshots_dir.glob(".staging-*"):
        if p.is_dir() and now - p.stat().st_mtime > stale_seconds:
            remove(p, dry_run)


def prune_snapshots(root: Path, dry_run: bool) -> None:
    data_dir = root / "data"

    # Legacy single-device layout (the auto-registered default device from
    # before multi-device support existed).
    _prune_one_snapshot_dir(data_dir, data_dir / "snapshots", dry_run)

    # Device-aware layout: data/devices/<device_id>/snapshots. Always
    # processed alongside the legacy layout above - previously this only
    # ran when --per-device was explicitly passed, which meant a forgotten
    # flag silently left every non-legacy device's snapshots unpruned
    # forever, with no warning.
    devices_dir = data_dir / "devices"
    if not devices_dir.is_dir():
        return
    for device_path in sorted(devices_dir.iterdir()):
        if not device_path.is_dir():
            continue
        _prune_one_snapshot_dir(device_path, device_path / "snapshots", dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform deletions; default is dry-run")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--per-device",
        action="store_true",
        help="deprecated, no-op: snapshot pruning always covers both the legacy "
        "and per-device layouts now; kept only so existing invocations "
        "that pass this flag don't break",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    dry_run = not args.apply
    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"Storage retention mode: {mode}")
    prune_backup_sets(root, dry_run)
    prune_snapshots(root, dry_run)
    print("Uploads were not modified; media deletion requires application-aware review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
