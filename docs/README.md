# Hirkanet

**Application Delivery. Cyber Security. Assured.**

Hirkanet is a web application that evaluates firewall policy access requests against real, collected device configuration — inspired by Tufin SecureTrack, built for FortiGate. Its core policy-evaluation engine, **SecureTrack‑Lite**, ranks candidate policies by least-privilege fit rather than just returning a yes/no answer, so an operator can see *why* a request would or wouldn't be allowed and what the closest safer alternative looks like. It also includes a **Policy Risk Assessment** service that automatically scores every collected policy on a 0–100 risk scale across four weighted dimensions (address scope, logging gaps, config weaknesses, staleness) and provides actionable remediation guidance per finding.

The application supports multiple registered FortiGate devices, each with its own encrypted credentials, its own collected snapshot data, and its own set of authorized client users — managed entirely through an admin panel, with no manual file editing required.

> Decision support, not a packet simulator: SecureTrack‑Lite's ranking is heuristic. It does not model every FortiGate feature (NAT, UTM profiles, SD-WAN rules, etc.) and its output should inform, not replace, direct verification against the device. See [`docs/EVALUATION.md`](docs/EVALUATION.md).

---

## Features

- **Policy evaluation** — submit a source, destination, and service (or a batch CSV of many) and get back ranked candidate policies, scored by coverage, interface alignment, and least-privilege fit
- **Policy risk assessment** — automated scoring of every collected policy on a 0–100 risk scale across four dimensions (address scope, logging gaps, config weaknesses, staleness), with per-policy remediation guidance and filterable results. Gated behind its own subscription; admins grant access per user
- **Multi-device inventory** — admins register any number of FortiGate devices, each with its own API host, credentials (encrypted at rest, never displayed again after entry), VDOM, and collection settings
- **Per-device sync** — a "Sync Now" button runs the collector for a single device on demand, in addition to (or instead of) a scheduled cron job
- **Device assignment** — admins grant individual client users access to specific devices; a client only ever sees and evaluates against devices they've been assigned, enforced at every entry point (page load, single evaluation, batch evaluation)
- **Admin panel** — user management, service subscriptions, and device inventory
- **Session-based auth** with CSRF protection, database-backed login rate limiting, and audit-logged admin actions
- **Atomic, checksum-verified snapshots** — each collection run is immutable and versioned; the evaluator never reads a snapshot that's still being written
- **Structured JSON logging**, with an optional Elastic (Elasticsearch/Logstash/Kibana/Filebeat) stack for centralized observability

---

## Architecture

Full details, verified against the running codebase rather than written from memory, live in **[`docs/architecture.md`](docs/architecture.md)**. In short:

| Layer | Where |
|---|---|
| Web app (admin panel, client UI, session auth) | Flask, `api/app.py` + `admin/`, `client/`, `main/`, `auth/` blueprints |
| Policy evaluation engine | `engine/` — snapshot loading, CIDR matching, interface selection, ranking |
| Policy risk assessment | `engine/risk_assessor.py` + `services/risk_assessment.py` — 4-dimension scoring, remediation guidance, subscription-gated access |
| Device collection | `collectors/fortigate_collector.py` (core) + `collectors/sync_service.py` (per-device, admin-triggered) |
| Data models | `models.py` (Flask-SQLAlchemy, primary schema) |
| Schema migrations | `migrations/` — Alembic, the single source of schema truth |
| Logging/observability | `logging_config.py`, `gunicorn_logging.py`, optional `docker-compose.elastic.yml` stack |

---

## Tech stack

- **Python 3.12**, **Flask 3** (Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Migrate/Alembic)
- **PostgreSQL** in production, **SQLite** as a zero-config local-dev fallback
- **Gunicorn** as the production WSGI server
- **Docker Compose** for orchestration; a separate, optional Compose project for the Elastic stack
- **Pytest** — a broad test suite (166 tests at last count) across models, migrations, collection, evaluation, authorization, and infrastructure

---

## Project structure

```
hirkanet/
├── api/              Flask app factory, login/CSRF/error handling, CLI commands
├── admin/            Admin panel routes (users, services, devices)
├── client/           Client-facing routes (dashboard, policy evaluation, risk assessment) + access control
├── main/             Root URL redirect, context processor
├── auth/             Login forms, rate limiting
├── engine/           Evaluation engine, risk assessor, snapshot store, CIDR/interface logic
├── collectors/       FortiGate REST collector + per-device sync service
├── services/         Service layer (policy search, risk assessment) with snapshot loading, filtering, pagination
├── validation/       Input validation for admin, evaluation, catalog, and risk assessment requests
├── models.py          Primary Flask-SQLAlchemy schema
├── db_url.py          Shared DB URL resolution
├── database_transactions.py   Transaction/error-handling helpers
├── secret_crypto.py / secret_utils.py / security.py   Secrets & credential handling
├── migrations/        Alembic migration history
├── templates/          Jinja2 templates (admin, client, auth, errors)
├── static/             CSS/JS/images
├── scripts/            Storage monitoring/retention, Postgres backup/restore
├── elk/                Elastic stack config (certs, Logstash pipeline)
├── docs/               Architecture, deployment, database, logging, security docs
└── tests/              33 test files
```

---

## Getting started

### Option A — Docker Compose (recommended, closest to production)

**Prerequisites:** Docker, Docker Compose.

```bash
cp .env.example .env
chmod 600 .env
# edit .env: set real values for SECRET_KEY, POSTGRES_PASSWORD,
# BOOTSTRAP_ADMIN_USERNAME/PASSWORD, and — since it's missing from the
# template — add DEVICE_CREDENTIAL_KEY yourself (see Configuration below)
```

The application container runs as a fixed non-root UID (`10001`). Create and prepare the host-mounted directories before first start — `data/` is a Docker-managed named volume and needs no host setup, but `uploads/` and `static/uploads/` are bind mounts:

```bash
mkdir -p uploads backups/postgres
sudo chown -R 10001:10001 uploads
```

```bash
docker compose up -d --build
```

This starts `db` (Postgres), runs `migrate` (schema migrations + default data seeding, one-shot), then starts `app` (the main Flask application, on `127.0.0.1:5000`).

```bash
docker compose logs migrate --tail=30    # confirm migrations applied cleanly
docker compose ps -a                     # confirm everything is healthy
```

Full deployment details — secrets, TLS, backups, storage monitoring — are in [`docs/depoly-readme.md`](docs/depoly-readme.md).

### Option B — Local development without Docker (SQLite)

**Prerequisites:** Python 3.12.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export APP_ENV=development
export SECRET_KEY=dev-secret-key
export DEVICE_CREDENTIAL_KEY=dev-credential-key
export BOOTSTRAP_ADMIN_USERNAME=admin
export BOOTSTRAP_ADMIN_PASSWORD=change-me-please-12

python -m flask --app api.app db upgrade
python -m flask --app api.app seed-defaults
python -m flask --app api.app run --debug
```

Open `http://127.0.0.1:5000` and log in with the bootstrap admin credentials above. This uses a local `fortigate_policy.db` SQLite file — no Postgres required.

---

## Configuration

Every environment variable the application reads is documented in **[`.env.example`](.env.example)**, grouped by concern (application runtime, initial admin account, PostgreSQL, Elastic Stack, FortiGate collector). Copy it and fill in real values:

```bash
cp .env.example .env
chmod 600 .env
```

> ⚠️ **`DEVICE_CREDENTIAL_KEY` is missing from `.env.example` — this will crash the app.** It encrypts device API keys/credentials at rest and is `required` whenever `APP_ENV=production` (which `.env.example` sets by default). Verified directly: with `APP_ENV=production` and no `DEVICE_CREDENTIAL_KEY` set, saving any device's API key raises `RuntimeError: DEVICE_CREDENTIAL_KEY_FILE or DEVICE_CREDENTIAL_KEY is required` the moment an admin tries to add or edit a device. **Add it to `.env` manually before deploying:**
> ```
> DEVICE_CREDENTIAL_KEY=<openssl rand -hex 32>
> ```
> Losing or rotating this value afterward makes every already-stored device credential undecryptable.

Other values worth understanding before deploying:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing |
| `DEVICE_CREDENTIAL_KEY` | **See warning above — not in the template, must be added manually** |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Database credentials — only take effect the *first* time the `postgres_data` volume is initialized |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | The first admin account, created once if no users exist |
| `ELASTIC_PASSWORD` / `KIBANA_PASSWORD` / `LOGSTASH_PASSWORD` / `KIBANA_*_ENCRYPTION_KEY` | Only needed if running the optional Elastic stack |
| `FORTIGATE_HOST` / `FORTIGATE_TOKEN` / etc. | Only needed for the legacy standalone collector CLI — device credentials added through the admin panel are stored per-device in the database instead |

---

## Working with devices

1. Log in as an admin and go to **Devices** in the admin panel.
2. **Add Device** — name, API host, VDOM, and credentials (API key, or username/password for future device types). Credential fields are write-only: once saved, they're never displayed again, and leaving them blank on an edit keeps the existing value.
3. **Sync Now** to run a collection immediately, or rely on a scheduled cron job calling `collectors/fortigate_collector.py` directly.
4. **Client Access** to grant specific client users evaluation access to that device.
5. Clients see only their assigned, active devices in the policy evaluation page's device selector.

Existing single-device installs are migrated forward automatically: the first time the app starts after upgrading, the pre-existing `data/` directory is registered as a device named "Default FortiGate" — no snapshot files are moved.

---

## Testing

```bash
export SECRET_KEY=testkey APP_ENV=development DEVICE_CREDENTIAL_KEY=testcredkey
pytest tests/ -q
```

`requirements.txt` includes everything needed to run the suite (`pytest`, `PyYAML` for the tests that parse `docker-compose.yml` directly, etc.) — no separate test-dependencies file.

---

## Logging & observability

Structured JSON logs by default (`LOG_FORMAT=json`, gated by `LOG_LEVEL`). An optional, separate Compose project brings up a full Elastic stack (Elasticsearch, Logstash, Kibana, Filebeat) with mutual TLS between components:

```bash
docker compose -f docker-compose.elastic.yml up -d --build
```

See [`docs/ELK-SETUP.md`](docs/ELK-SETUP.md) and [`docs/LOGGING-GUIDE.md`](docs/LOGGING-GUIDE.md).

---

## Documentation index

| Doc | Covers |
|---|---|
| [`architecture.md`](docs/architecture.md) | Full system architecture, verified against the running code |
| [`depoly-readme.md`](docs/depoly-readme.md) | Deployment: secrets, directories, first-time setup |
| [`database-readme.md`](docs/database-readme.md) | Migrations, backup, retention, PostgreSQL operations |
| [`DATABASE-MIGRATIONS.md`](docs/DATABASE-MIGRATIONS.md) | Alembic migration workflow |
| [`FORTIGATE-SNAPSHOTS.md`](docs/FORTIGATE-SNAPSHOTS.md) | Atomic snapshot storage design |
| [`EVALUATION.md`](docs/EVALUATION.md) | What the evaluation engine does and doesn't model |
| [`USER_MANUAL.md`](docs/USER_MANUAL.md) | End-user guide to the web application |
| [`HTTPS-DEPLOYMENT.md`](docs/HTTPS-DEPLOYMENT.md) | TLS/reverse-proxy setup |
| [`LOGGING-GUIDE.md`](docs/LOGGING-GUIDE.md) / [`ELK-SETUP.md`](docs/ELK-SETUP.md) | Logging pipeline and the optional Elastic stack |
| [`STORAGE-MONITORING.md`](docs/STORAGE-MONITORING.md) | Disk usage monitoring and retention policy |
| [`POSTGRES-BACKUP-RESTORE.md`](docs/POSTGRES-BACKUP-RESTORE.md) | Backup and restore procedures |
| [`LOGIN-RATE-LIMITING-CHANGES.md`](docs/LOGIN-RATE-LIMITING-CHANGES.md) | Login rate limiting design |
| [`COMPOSE-DEPLOYMENT.md`](docs/COMPOSE-DEPLOYMENT.md) | Why the app and Elastic stack are split into two Compose projects |
| [`MULTI-VENDOR-PLAN.md`](docs/MULTI-VENDOR-PLAN.md) | Planning notes for multi-vendor device support |
| [`similar-projects.md`](docs/similar-projects.md) | Comparable tools in the network security/observability space |

`docs/README.md` predates the multi-device, admin panel, and API-service work described above and is kept only for history — this file is the current entry point.

---

## Known limitations

A concrete, actively-maintained list — not vague "future work" — lives in `docs/architecture.md` section 11, and currently includes items such as synchronous device sync's worker-timeout risk at scale, Docker secrets not yet being wired up for the main app stack, and some orphaned legacy code pending removal. Worth reading before relying on this in a security-sensitive production deployment.

---

## License

No license file is currently present in this repository. Treat all rights as reserved until one is added.
