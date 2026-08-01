# PostgreSQL Backup and Restore

Hirkanet stores application identities, services, subscriptions, blog content,
and Alembic migration state in the named Docker volume `postgres_data`.
A Docker volume is persistent storage, but it is not a backup.

## Backup policy

The included workflow creates PostgreSQL custom-format dumps. Each successful
backup set contains:

- `*.dump` — compressed custom-format archive
- `*.dump.sha256` — integrity checksum
- `*.dump.meta` — database/version metadata and restore-test status

By default, every backup is restored into a disposable database and validated
before it is marked successful. Backups older than 14 days are removed, while
at least the seven newest archives are retained.

## Create and test a backup

From the directory containing `docker-compose.yml`:

```bash
./scripts/postgres-backup.sh
```

The script never reads the PostgreSQL password on the host. `pg_dump` executes
inside the database container and reads `/run/secrets/postgres_password`.

To change retention:

```bash
RETENTION_DAYS=30 KEEP_MINIMUM=14 ./scripts/postgres-backup.sh
```

Skipping the restore test is available only for exceptional situations:

```bash
./scripts/postgres-backup.sh --no-restore-test
```

A skipped restore test is recorded in the metadata and should not be treated as
a fully verified production backup.

## Re-test an existing backup

```bash
./scripts/postgres-restore-test.sh backups/postgres/<backup>.dump
```

The test performs these checks:

1. Verifies the SHA-256 checksum when present.
2. Validates the archive with `pg_restore --list`.
3. Creates a uniquely named disposable database.
4. Restores with `--exit-on-error`.
5. Confirms the application tables and `alembic_version` exist.
6. Drops the disposable database even if the test fails.

## Restore into a separate database

The safe default is to restore beside production first:

```bash
./scripts/postgres-restore.sh \
  --backup backups/postgres/<backup>.dump \
  --target-db hirkanet_recovery \
  --confirm-restore
```

Inspect and test the recovered database before any cutover.

## Production replacement

Restoring over the configured production database is deliberately blocked
unless `--allow-production-target` is supplied. This operation requires an
outage and destroys the current target database.

Required procedure:

1. Announce maintenance and stop write traffic.
2. Create a fresh backup of the current production database.
3. Verify the selected recovery backup using `postgres-restore-test.sh`.
4. Run:

```bash
./scripts/postgres-restore.sh \
  --backup backups/postgres/<backup>.dump \
  --target-db "$POSTGRES_DB" \
  --confirm-restore \
  --allow-production-target
```

5. Restart migration and application services:

```bash
docker compose up -d migrate app
```

6. Verify `/readyz`, login, subscriptions, and representative blog records.

## Off-host storage

The local `backups/` directory is excluded from Git but remains on the same
host. Copy successful backup sets to encrypted off-host storage. A recommended
minimum is:

- Daily backups retained for 14 days
- Weekly backups retained for 8 weeks
- Monthly backups retained for 12 months
- At least one copy in a separate failure domain

The exact retention policy must match the business recovery-point objective.

## Scheduling

Example daily systemd timer or cron command:

```cron
15 2 * * * cd /opt/hirkanet && ./scripts/postgres-backup.sh >> /var/log/hirkanet-postgres-backup.log 2>&1
```

Run scheduled jobs under a dedicated account with access to Docker and the
backup destination. Docker-group membership is effectively privileged and must
be tightly controlled.

## Recovery assurance

A backup is not considered operationally valid solely because `pg_dump`
returned success. Monitor:

- Age of the newest `restore_test=passed` backup
- Backup file size changes
- Free disk space
- Off-host copy completion
- Periodic recovery drills on another host
