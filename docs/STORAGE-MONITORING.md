# Storage Monitoring and Retention

Hirkanet separates **monitoring** from **deletion**. Monitoring is read-only. Retention defaults to dry-run and deletes only artifacts that are safe to remove by policy.

## What is monitored

Run:

```bash
./scripts/storage-monitor.py
```

Machine-readable output:

```bash
./scripts/storage-monitor.py --json
```

The monitor checks:

- Host filesystem utilization
- PostgreSQL database size
- PostgreSQL data-volume utilization
- Total PostgreSQL backup storage
- Age of the newest restore-tested PostgreSQL backup
- FortiGate snapshot storage and snapshot count
- Stale FortiGate staging directories
- Validity of the active FortiGate snapshot pointer
- Blog and generic upload storage

Exit codes:

- `0`: healthy
- `1`: warning or unknown dependency
- `2`: critical

## Default thresholds

| Metric | Warning | Critical |
|---|---:|---:|
| Host filesystem | 80% | 90% |
| PostgreSQL volume | 80% | 90% |
| PostgreSQL database | 5 GiB | 10 GiB |
| Latest verified backup age | 26 hours | 48 hours |
| Backup directory | 20 GiB | 40 GiB |
| FortiGate snapshots | 5 GiB | 10 GiB |
| Upload storage | 5 GiB | 10 GiB |

All thresholds can be overridden with environment variables documented in `.env.example`.

## Retention policy

Preview retention actions:

```bash
./scripts/storage-retention.py
```

Apply them explicitly:

```bash
./scripts/storage-retention.py --apply
```

The retention tool handles only:

- PostgreSQL backup sets older than `RETENTION_DAYS`, while preserving at least `KEEP_MINIMUM`
- Abandoned `.partial` and `.tmp` backup files older than `BACKUP_PARTIAL_MAX_AGE_HOURS`
- Superseded FortiGate snapshots beyond `FORTIGATE_KEEP_SNAPSHOTS`
- Stale `.staging-*` FortiGate directories older than `FORTIGATE_STAGING_MAX_AGE_HOURS`

The active FortiGate snapshot is always protected.

## Upload retention

Uploaded blog media is monitored but **never deleted automatically**. A file may still be referenced by a blog post, cached page, external link, or backup. Media cleanup must be application-aware and reviewed before deletion.

## Scheduling

Example daily monitor:

```cron
15 2 * * * cd /srv/hirkanet && ./scripts/storage-monitor.py --json >> /var/log/hirkanet-storage.jsonl
```

Example daily retention preview and weekly apply:

```cron
30 2 * * * cd /srv/hirkanet && ./scripts/storage-retention.py >> /var/log/hirkanet-retention-preview.log
45 2 * * 0 cd /srv/hirkanet && ./scripts/storage-retention.py --apply >> /var/log/hirkanet-retention.log
```

Send non-zero monitor exit codes to the site alerting system. Do not rely only on local log files.

## Operational policy

- PostgreSQL backups remain governed by `POSTGRES-BACKUP-RESTORE.md` and must be copied off-host.
- A backup is considered current only when its metadata reports `restore_test=passed`.
- FortiGate snapshots contain sensitive network data and must be protected like database backups.
- Capacity alerts should be investigated before changing retention limits.
- Retention must not replace backups, restore tests, or off-host replication.
