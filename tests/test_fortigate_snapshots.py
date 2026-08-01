import json
from argparse import Namespace
from pathlib import Path

import pytest

from collectors import fortigate_collector as collector
from engine.snapshot_store import SnapshotError, load_snapshot_dataset


def sample_dataset(marker="one"):
    return {
        "policies.json": [{"policyid": 1, "name": marker}],
        "addresses.json": [{"name": f"address-{marker}"}],
        "services.json": [{"name": f"service-{marker}"}],
        "routes.json": [{"dst": "0.0.0.0/0", "device": "port1"}],
        "interfaces.json": [{"name": "port1"}],
    }


def args():
    return Namespace(
        host="https://fortigate.example.test",
        vdom="root",
        scheme="https",
        verify=True,
        skip_monitor_routes=False,
    )


def test_publish_creates_versioned_snapshot_and_atomic_pointer(tmp_path):
    snapshot_id, snapshot_dir, manifest = collector.publish_snapshot(
        tmp_path, sample_dataset(), args()
    )

    pointer = json.loads((tmp_path / "current.json").read_text())
    assert pointer["snapshot_id"] == snapshot_id
    assert pointer["path"] == f"snapshots/{snapshot_id}"
    assert snapshot_dir == tmp_path / "snapshots" / snapshot_id
    assert manifest["source"]["host"] == "fortigate.example.test"
    assert not list(tmp_path.glob(".current.json.*.tmp"))
    assert not list((tmp_path / "snapshots").glob(".staging-*"))

    location, dataset, loaded_manifest = load_snapshot_dataset(tmp_path)
    assert location.snapshot_id == snapshot_id
    assert dataset["policies.json"][0]["name"] == "one"
    assert loaded_manifest["files"]["policies.json"]["records"] == 1


def test_failed_publish_does_not_change_active_pointer(tmp_path, monkeypatch):
    first_id, _, _ = collector.publish_snapshot(tmp_path, sample_dataset("first"), args())
    original_pointer = (tmp_path / "current.json").read_bytes()
    original_write = collector._write_bytes_durable

    def fail_on_services(path, payload):
        if path.name == "services.json":
            raise OSError("simulated disk failure")
        return original_write(path, payload)

    monkeypatch.setattr(collector, "_write_bytes_durable", fail_on_services)
    with pytest.raises(OSError):
        collector.publish_snapshot(tmp_path, sample_dataset("second"), args())

    assert (tmp_path / "current.json").read_bytes() == original_pointer
    assert load_snapshot_dataset(tmp_path)[0].snapshot_id == first_id
    assert not list((tmp_path / "snapshots").glob(".staging-*"))


def test_checksum_tampering_is_rejected(tmp_path):
    _, snapshot_dir, _ = collector.publish_snapshot(tmp_path, sample_dataset(), args())
    (snapshot_dir / "policies.json").write_text("[]\n")

    with pytest.raises(SnapshotError, match="checksum mismatch"):
        load_snapshot_dataset(tmp_path)


def test_retention_keeps_active_and_requested_count(tmp_path):
    ids = []
    for marker in ("one", "two", "three"):
        snapshot_id, _, _ = collector.publish_snapshot(tmp_path, sample_dataset(marker), args())
        ids.append(snapshot_id)

    collector.prune_snapshots(tmp_path, ids[-1], keep=2)
    remaining = {path.name for path in (tmp_path / "snapshots").iterdir() if path.is_dir()}
    assert ids[-1] in remaining
    assert len(remaining) == 2


def test_flat_legacy_data_remains_readable_for_controlled_migration(tmp_path):
    for filename, payload in sample_dataset().items():
        (tmp_path / filename).write_text(json.dumps(payload))

    location, dataset, manifest = load_snapshot_dataset(tmp_path)
    assert location.legacy is True
    assert location.snapshot_id == "legacy-flat-data"
    assert dataset["addresses.json"][0]["name"] == "address-one"
    assert manifest["legacy"] is True
