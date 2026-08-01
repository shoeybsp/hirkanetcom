# FortiGate Atomic Snapshot Storage

Hirkanet stores each completed FortiGate collection as an immutable, versioned snapshot. The evaluator never reads files while the collector is writing them.

## Directory layout

```text
data/
├── current.json
└── snapshots/
    ├── 20260731T120000.000000Z-a1b2c3d4/
    │   ├── manifest.json
    │   ├── policies.json
    │   ├── addresses.json
    │   ├── services.json
    │   ├── routes.json
    │   └── interfaces.json
    └── ...
```

`current.json` is the only mutable publication pointer. It is replaced atomically after every required JSON file and the manifest have been written, flushed, and the completed staging directory has been renamed into place.

## Collection transaction

The collector performs these steps:

1. Acquires `data/.collector.lock` to prevent concurrent publication.
2. Collects every required FortiGate resource into memory.
3. Writes all files into `data/snapshots/.staging-<snapshot-id>/`.
4. Writes `manifest.json` with source metadata, record counts, byte sizes, and SHA-256 checksums.
5. Flushes files and directories to storage.
6. Renames the staging directory to its immutable final snapshot ID.
7. Atomically replaces `data/current.json`.
8. Removes old completed snapshots according to retention.

Any failure before step 7 leaves the previous active pointer unchanged. The evaluator therefore continues using the last complete snapshot.

## Run the collector

```bash
export FORTIGATE_HOST=192.168.1.99
export FORTIGATE_TOKEN='your-api-token'
export FORTIGATE_VDOM=root
python collectors/fortigate_collector.py
```

Keep a different number of completed snapshots:

```bash
python collectors/fortigate_collector.py --keep-snapshots 20
```

The environment equivalent is:

```bash
export FORTIGATE_KEEP_SNAPSHOTS=20
```

The minimum is one snapshot. Ten snapshots are retained by default.

## Evaluator behavior

At initialization, the evaluator:

1. Reads `current.json` once.
2. Resolves exactly one immutable snapshot directory.
3. Verifies the manifest, required files, record counts, and SHA-256 checksums.
4. Loads all policy, address, service, route, and interface data from that same snapshot.

The web process checks the active snapshot ID and reloads the evaluator automatically after a newly published snapshot becomes active.

## Rollback

To roll back, replace `current.json` atomically with a pointer to an existing retained snapshot. Do not edit snapshot contents.

Example pointer:

```json
{
  "schema_version": 1,
  "snapshot_id": "20260731T120000.000000Z-a1b2c3d4",
  "path": "snapshots/20260731T120000.000000Z-a1b2c3d4",
  "published_at": "2026-07-31T12:00:01+00:00"
}
```

Write to a temporary file in `data/` and use `mv` on the same filesystem so replacement remains atomic.

## Backup scope

Back up all of:

```text
data/current.json
data/snapshots/
```

Snapshots may contain sensitive firewall rules, object names, routing information, and internal network addresses. Protect backups accordingly.

## Legacy flat-file compatibility

The evaluator can still read the old flat `data/*.json` layout only as a controlled migration fallback when `current.json` does not exist. New collections never write the legacy layout.
