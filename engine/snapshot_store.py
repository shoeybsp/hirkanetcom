"""Atomic, versioned storage for collected FortiGate datasets."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_DATA_FILES = (
    "policies.json",
    "addresses.json",
    "services.json",
    "routes.json",
    "interfaces.json",
)
POINTER_FILE = "current.json"
SNAPSHOTS_DIR = "snapshots"
MANIFEST_FILE = "manifest.json"


class SnapshotError(RuntimeError):
    """Raised when a FortiGate snapshot is missing, invalid, or inconsistent."""


@dataclass(frozen=True)
class SnapshotLocation:
    snapshot_id: str
    path: Path
    legacy: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Could not read valid JSON from {path}") from exc


def resolve_active_snapshot(data_root: str | os.PathLike[str] = "data") -> SnapshotLocation:
    """Resolve one immutable snapshot from the active pointer.

    Legacy flat JSON files remain readable only to permit a controlled migration
    from older deployments. Newly collected data is always snapshot-based.
    """

    root = Path(data_root)
    pointer_path = root / POINTER_FILE
    if pointer_path.exists():
        pointer = _read_json(pointer_path)
        snapshot_id = str(pointer.get("snapshot_id", "")).strip()
        relative_path = str(pointer.get("path", "")).strip()
        if not snapshot_id or not relative_path:
            raise SnapshotError(f"Invalid active snapshot pointer: {pointer_path}")

        candidate = (root / relative_path).resolve()
        snapshots_root = (root / SNAPSHOTS_DIR).resolve()
        if snapshots_root != candidate.parent:
            raise SnapshotError("Active snapshot pointer escapes the snapshots directory")
        if candidate.name != snapshot_id or not candidate.is_dir():
            raise SnapshotError(f"Active snapshot directory does not exist: {candidate}")
        return SnapshotLocation(snapshot_id=snapshot_id, path=candidate)

    missing = [name for name in REQUIRED_DATA_FILES[:-1] if not (root / name).is_file()]
    if not missing:
        return SnapshotLocation(snapshot_id="legacy-flat-data", path=root.resolve(), legacy=True)

    raise SnapshotError(
        "No active FortiGate snapshot is available. Run collectors/fortigate_collector.py."
    )


def verify_snapshot(location: SnapshotLocation) -> dict[str, Any]:
    """Validate the manifest and checksums for a versioned snapshot."""

    if location.legacy:
        return {"snapshot_id": location.snapshot_id, "legacy": True}

    manifest_path = location.path / MANIFEST_FILE
    manifest = _read_json(manifest_path)
    if manifest.get("snapshot_id") != location.snapshot_id:
        raise SnapshotError("Snapshot manifest ID does not match the active pointer")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise SnapshotError("Snapshot manifest has no files map")

    for filename in REQUIRED_DATA_FILES:
        path = location.path / filename
        entry = files.get(filename)
        if not path.is_file() or not isinstance(entry, dict):
            raise SnapshotError(f"Snapshot is missing required file: {filename}")
        expected = entry.get("sha256")
        if not expected or sha256_file(path) != expected:
            raise SnapshotError(f"Snapshot checksum mismatch: {filename}")
        payload = _read_json(path)
        if not isinstance(payload, list):
            raise SnapshotError(f"Snapshot file must contain a JSON list: {filename}")
        if entry.get("records") != len(payload):
            raise SnapshotError(f"Snapshot record count mismatch: {filename}")

    return manifest


def load_snapshot_dataset(
    data_root: str | os.PathLike[str] = "data",
    *,
    verify: bool = True,
) -> tuple[SnapshotLocation, dict[str, list[Any]], dict[str, Any]]:
    """Load all dataset files from one resolved immutable snapshot."""

    location = resolve_active_snapshot(data_root)
    manifest = verify_snapshot(location) if verify else {}
    dataset: dict[str, list[Any]] = {}
    for filename in REQUIRED_DATA_FILES:
        path = location.path / filename
        if not path.exists() and location.legacy and filename == "interfaces.json":
            dataset[filename] = []
            continue
        payload = _read_json(path)
        if not isinstance(payload, list):
            raise SnapshotError(f"Dataset file must contain a JSON list: {path}")
        dataset[filename] = payload
    return location, dataset, manifest


def active_snapshot_id(data_root: str | os.PathLike[str] = "data") -> str | None:
    try:
        return resolve_active_snapshot(data_root).snapshot_id
    except SnapshotError:
        return None
