---
name: architecture
description: Overview of Hirkanet's system architecture and components
metadata:
  type: reference
---

# Hirkanet System Architecture

**Repository:** `hirkanetcom`

Hirkanet is a Flask-based web application that evaluates FortiGate firewall
policy access requests against collected device configuration, provides
a policy catalog for browsing and searching collected policies, and
scores policies by security risk with actionable remediation guidance.
It supports multiple registered devices, each with its own credentials,
collected snapshot data, and set of authorized client users.

Every claim below was verified against the actual codebase and, where
noted, against a running instance - not carried over from prior notes.

---
## 1. Web Application Layer

- **Framework:** Flask (Python 3.12)
- **App factory:** `api/app.py` - creates the Flask app, configures
  `TRUSTED_HOSTS`, `MAX_CONTENT_LENGTH`, proxy header trust, and registers
  blueprints.
- **Blueprints:**
  - `main/routes.py` - root URL redirect and context processor.
  - `auth/` - login forms (`forms.py`) and database-backed login rate
    limiting (`rate_limit.py`). `auth/user_store.py` is dead code left over
    from a pre-SQLAlchemy user store; it is not imported anywhere and
    `tests/test_no_legacy_user_store.py` expects it to be deleted.
  - `client/` - the client-facing dashboard, Policy Evaluation service, and
    Policy Catalog service (`routes.py`), plus authorization helpers
    (`access.py`).
  - `admin/` - the admin panel: user, service, and device management
    (`routes.py`).
- **Gunicorn:** Production WSGI server via `gunicorn.conf.py`. No explicit
  worker `timeout` is set, so it uses Gunicorn's default (30s) - relevant
  because device sync (section 3) runs synchronously inside a request.

---
## 2. Device Inventory & Multi-Device Support

Introduced to move the app from a single hardcoded FortiGate to an
admin-managed inventory of any number of devices, each independently
collected and independently assigned to clients.

- **`Device` model** (`models.py`) - one row per registered device: name,
  connection settings (`api_host`, `api_scheme`, `vdom`, `verify_ssl`,
  `timeout_seconds`, `skip_monitor_routes`, `keep_snapshots`), an isolated
  `data_dir` for its snapshots, `is_active`, and `last_sync_*` status
  fields. Credentials (`api_key`, `auth_username`, `auth_password`) are
  stored encrypted, never in plaintext.
- **`DeviceAssignment` model** - grants a specific client `User` access to
  evaluate policies against a specific `Device`. Both the assignment and
  the device must be active for access to be granted
  (`client/access.py::has_device_access`, `get_assigned_devices`).
- **Credential encryption:** `secret_crypto.py` uses Fernet, keyed by the
  `DEVICE_CREDENTIAL_KEY` secret (same `NAME`/`NAME_FILE` convention as
  `SECRET_KEY`, via `secret_utils.read_secret`). Required in production;
  falls back to an insecure development-only key otherwise. Losing or
  rotating this key makes previously stored device credentials
  undecryptable.
- **Admin UI** (`admin/routes.py`, `templates/admin/device_*.html`):
  - `/admin/devices` - list, create, edit, delete devices.
  - `/admin/devices/<id>/assignments` - assign/unassign client users.
  - `/admin/devices/<id>/sync` - trigger an on-demand collection (below).
- **Backward compatibility:** on first run after this feature was added,
  `models.py::_seed_defaults()` registers the pre-existing flat `data/`
  directory as a `Device` named "Default FortiGate" - no snapshot files are
  moved, so existing single-device installs keep working unmodified.

---
## 3. Data Collection Layer

- **Collector core:** `collectors/fortigate_collector.py` (~460 lines) -
  pulls policies, addresses, services, interfaces, and routes from a
  FortiGate's REST API; writes atomic, checksum-verified snapshots
  (`snapshots/<id>/*.json` + a `current.json` pointer) under a given output
  directory; prunes old snapshots; serializes concurrent runs against the
  same directory with an flock-based lock (`collector_lock`). Still
  runnable standalone via CLI/env vars (`FORTIGATE_HOST`, `FORTIGATE_TOKEN`,
  etc.) for anyone still using cron instead of the admin UI.
- **Per-device sync service:** `collectors/sync_service.py` (~210 lines) -
  bridges the admin "Sync Now" button to the collector core. Decrypts a
  `Device`'s stored credentials, builds the same argument shape the CLI
  would have built from flags, runs collection into that device's own
  `data_dir`, and records `last_sync_at` / `last_sync_status` /
  `last_sync_message` / `last_snapshot_id` on the `Device` row. Maps raw
  exceptions (auth failures, TLS errors, timeouts, connection errors) to
  short, actionable messages rather than surfacing raw exception text,
  since exception messages can otherwise embed request URLs.
- **Known limitation:** sync runs synchronously inside the Flask request
  that handles the button click. Fine for the mock/small-scale testing done
  so far; a FortiGate with a very large policy set could take long enough
  to hit Gunicorn's worker timeout. Moving sync to a background job is the
  fix if that happens in practice - not yet implemented.
- **Storage housekeeping is multi-device aware:** `scripts/storage-monitor.py`
  and `scripts/storage-retention.py` iterate both the legacy `data/`
  layout and every `data/devices/<id>/` directory. Two bugs were found and
  fixed while verifying this against a controlled multi-device fixture:
  the active-snapshot integrity check originally only ever read the
  single legacy `data/current.json`, producing a false CRITICAL alert on
  any install without a legacy device (each device has its own
  `current.json` under its own `data_dir`); and retention's per-device
  pruning was silently gated behind a `--per-device` flag that, if
  forgotten, meant snapshots for every non-legacy device were never
  pruned at all. Both scripts now cover every device unconditionally; the
  flag is still accepted by `storage-retention.py` for backward CLI
  compatibility but is now a documented no-op.

---
## 4. Evaluation Engine

- **Core:** `engine/evaluator.py` (`SecureTrackLite`) - loads one
  device's snapshot via `data_root`, ranks candidate policies by coverage,
  interface alignment, and least-privilege fit. Explicitly not a FortiGate
  packet-processing simulator; results are decision support only (this
  disclaimer is shown in the client UI).
  - `engine/cidr_tools.py` - CIDR/IP-range utilities.
  - `engine/interface_selector.py` - interface selection heuristics.
  - `engine/input_validation.py` - validates evaluation request input.
  - `engine/snapshot_store.py` - atomic snapshot resolution and checksum
    verification, parameterized by `data_root`.
- **Per-device engine cache:** `client/routes.py` keeps one
  `SecureTrackLite` instance per device id (`_engines`), reloading a
  device's entry only when that specific device's snapshot pointer
  changes. This means an admin sync is picked up by clients on their next
  request with no app restart, and syncing one device never invalidates or
  affects another device's cached engine. Verified live: patched a mock
  device's data, triggered Sync Now, and confirmed the same client session
  saw the new data immediately while a second device's cache stayed
  unaffected.
- **Authorization is enforced at three layers**, all backed by the same
  `client/access.py` helpers: the device `<select>` shown on the page only
  lists a client's own assigned+active devices; the single-evaluation POST
  route re-validates the submitted `device_id` against that same list; the
  batch-upload POST route does the same. A client attempting to reach an
  unassigned device gets a 403 with no snapshot data in the response, on
  all three paths (GET catalog, single POST, batch POST) - verified with a
  second client account under an intentionally cross-device attack test.

---
## 4b. Policy Search / Catalog Service

- **Purpose:** Allows authenticated clients to browse, search, and filter
  collected firewall policies across their assigned devices. No subscription
  gating — accessible to any client with device access.
- **Service layer:** `services/policy_search.py` (`PolicySearchService`) -
  loads a device's snapshot via `engine/snapshot_store.py::load_snapshot_dataset`,
  normalizes policy data, and provides filtering/sorting/pagination. Also
  exposes `get_filter_options()` to supply unique address and service names
  for autocomplete dropdowns.
- **Client routes** (`client/routes.py`):
  - `GET /client/policies` — server-rendered policy catalog page with
    device selector, filter form, and results table.
  - `GET|POST /client/policies/results` — JSON endpoint returning filtered
    policies with pagination. Used by the catalog page's JavaScript.
- **Validation:** `validation/policies.py` — validates query parameters
  (action, status, limit, offset, sort_by, sort_order).
- **Filter options:** Address and service lists are extracted from the
  snapshot on page load and passed to the template for searchable dropdown
  autocomplete. The dropdowns filter client-side as the user types.
- **Authorization:** Same `client/access.py` helpers as Policy Evaluation.
  Device access is enforced at both the catalog page route and the JSON
  results endpoint.

---
## 4c. Policy Risk Assessment Service

- **Purpose:** Scores every policy in a device's snapshot on a 0–100 risk
  scale across four weighted dimensions, surfaces the highest-risk policies,
  and provides actionable remediation guidance per finding. Access is gated
  behind the `policy_risk_assessment` subscription (admin must grant it per
  user), unlike Policy Catalog which is open to any authenticated client
  with device access.

- **Engine:** `engine/risk_assessor.py` (`PolicyRiskAssessor`, ~430 lines) —
  loads one device's snapshot via `engine/snapshot_store.py`, builds address
  and service lookup maps, and scores every policy. Dimensions and weights:

  | Dimension            | Weight | What it checks |
  |----------------------|--------|----------------|
  | Address Scope        | 35%    | Rules using `all`, `0.0.0.0/0`, or wildcard addresses |
  | Logging Gaps         | 25%    | Accept rules without logging enabled |
  | Config Weakness      | 25%    | Disabled rules, overly broad service definitions, excessive per-rule timeouts (>7200s), TLS inspection gaps |
  | Staleness            | 15%    | Rules last modified >90 days ago |

  Risk levels: `critical` (≥80), `high` (≥60), `medium` (≥40), `low`
  (≥20), `info` (<20). Each dimension produces a `RiskFactor` with its
  own score and list of `Finding` objects. Final score is the weighted sum,
  clamped to 0–100. Each policy result includes a `remediation` list of
  actionable items (e.g. "Add logging", "Replace 'all' address with
  specific subnet").

- **Service layer:** `services/risk_assessment.py` (`RiskAssessmentService`,
  ~100 lines) — follows the same snapshot-loading pattern as
  `PolicySearchService`. `get_assessment()` supports filtering by
  `risk_level`, `dimension`, `min_score`, and policy `name`, with pagination
  (`limit`/`offset`) and sorting (`sort_by`/`sort_order`). Also exposes
  `get_policy_detail(policy_id)` for the modal view of a single policy's
  factors and remediation items, and `get_summary()` for the dashboard
  summary cards (counts per risk level, average score).

- **Validation:** `validation/risk_assessment.py` — validates query
  parameters for the assessment and detail endpoints (risk_level, dimension,
  min_score, limit, offset, sort_by, sort_order).

- **Client routes** (`client/routes.py`):
  - `GET /client/risk-assessment` — server-rendered page with device
    selector. Requires `policy_risk_assessment` subscription.
  - `GET|POST /client/risk-assessment/results` — JSON endpoint returning
    filtered, paginated risk results plus summary statistics. Used by the
    page's JavaScript.
  - `GET /client/risk-assessment/policy/<policy_id>` — JSON endpoint
    returning a single policy's full risk breakdown (factors, findings,
    remediation).

- **Template:** `templates/client/risk_assessment.html` (~500 lines) —
  device selector, filter controls (risk level, dimension, min score, name),
  summary cards row (total policies, average score, counts per risk level),
  sortable results table with inline score bars and risk-level badges, and a
  detail modal showing all four risk factors with their findings and
  remediation items.

- **Authorization:** Two-layer gating — `@subscription_required(
  "policy_risk_assessment")` on every route (returns 403 if the user lacks
  the subscription), plus `has_device_access()` to ensure the user can only
  see data for their assigned devices. The admin must grant the
  `policy_risk_assessment` subscription via `/admin/services` before a client
  can access the service.

---
## 5. Persistence Layer

- **Database:** PostgreSQL in production (`docker-compose.yml`'s `db`
  service), or SQLite as a zero-config fallback for local development
  (`models.py::_default_database_url`). Resolution order: `DATABASE_URL` >
  `POSTGRES_HOST` > SQLite file `fortigate_policy.db` in the repo root.
- **SQLite foreign-key enforcement:** SQLite does not enforce `FOREIGN
  KEY`/`ON DELETE CASCADE` constraints unless told to per-connection.
  `models.py` registers a `PRAGMA foreign_keys=ON` connect-event listener
  so local/dev/test runs actually get the same cascade-delete behavior
  Postgres provides natively. Discovered by live-testing device deletion,
  where an orphaned `DeviceAssignment` row survived a `Device` delete under
  SQLite before this was added.
- **Migrations:** Alembic scripts in `migrations/versions/`, applied
  sequentially - most recent adds `devices` and `device_assignments`.
- **Backup/Restore:** `scripts/postgres-backup.sh`,
  `scripts/postgres-restore.sh`, `scripts/postgres-restore-test.sh`.
- **Secrets management - two different states depending on which compose
  file you're looking at:**
  - `docker-compose.elastic.yml` (the ELK/observability stack) has a
    fully-wired `secrets:` block: every relevant service (`elasticsearch`,
    `elastic-init`, `logstash`, `kibana`) declares its `secrets:` list and
    reads values via the `NAME_FILE` convention from files under
    `${SECRETS_DIR:-./secrets}/`. This works correctly as shipped.
  - `docker-compose.yml` (the app itself: `db`, `migrate`, `app`) has
    **no** `secrets:` block at all - it only uses `env_file: .env`. The
    application code (`secret_utils.read_secret`) already supports the
    `NAME_FILE` convention and would work with Docker secrets if the
    compose file wired them up, but that wiring was never done for the
    main app stack. `tests/test_secret_configuration.py` documents this
    expectation and fails on it (`services["db"]["secrets"]` doesn't
    exist). Plain `.env` works correctly in the meantime; it's a security
    hardening gap (secrets sit in the container's process environment
    rather than a mounted file), not a functional one.
- **`.gitignore` does not exist in this repository.** Confirmed by diffing
  against the repo's own `SHA256SUMS` manifest, which lists it (and five
  other root-level files) as expected but absent from this snapshot of the
  repo.

---
## 6. Logging & Observability

- **Logging Configuration:** `logging_config.py` and `gunicorn_logging.py`
  produce structured JSON logs (`LOG_FORMAT=json`), gated by `LOG_LEVEL`.
- **ELK Stack:** `docker-compose.elastic.yml` runs Elasticsearch, Logstash,
  Kibana, and Filebeat, with mutual TLS between them (`elk/setup-certs.sh`,
  `elk/rotate-elastic-ca.sh`) and a Logstash pipeline in
  `elk/logstash/pipeline/logstash.conf`. See `docs/ELK-SETUP.md` and
  `docs/ELASTIC-STACK-IMPLEMENTATION-REPORT.md`.
- **Audit events:** admin actions relevant to devices
  (`audit_device_created`, `audit_device_updated`, `audit_device_deleted`,
  `audit_device_assignments_updated`) and sync outcomes
  (`device_sync_requested`, `device_sync_succeeded`, `device_sync_failed`)
  are logged with structured `event_type` fields, consistent with the
  existing `audit_user_*` / `audit_device_created` pattern already used for
  users and services.

---
## 7. Security Controls

- **CSRF Protection:** `security.py`, tested by
  `tests/test_csrf_protection.py`.
- **Container user is a pinned, non-root UID/GID (10001:10001)** in the
  `Dockerfile`, added after discovering that an unpinned system user (whose
  UID depends on base-image internals) caused "Sync Now" to fail with a
  host bind-mount permission error the first time it tried to create a new
  per-device snapshot directory.
- **`data/` is a Docker-managed named volume** (`hirkanet_data:/app/data`
  in `docker-compose.yml`), not a host bind mount. The Dockerfile explicitly
  creates `/app/data` with `uid 10001` ownership before `USER app`
  (`RUN mkdir -p /app/data ... && chown -R app:app /app`), so Docker's
  first-time volume population - which copies a mount path's existing
  image content and ownership into a newly created named volume - always
  has correct ownership to copy, regardless of what the host build machine
  happens to contain. `uploads/` and `static/uploads/` remain host bind
  mounts and still need an explicit host-side `chown -R 10001:10001`;
  documented in `docs/depoly-readme.md`.
- **TLS/Hostname Verification:** `docs/HTTPS-DEPLOYMENT.md`,
  `tests/test_full_tls_hostname_verification.py`.
- **Rate Limiting:** database-backed login rate limiting
  (`docs/LOGIN-RATE-LIMITING-CHANGES.md`).
- **Device credential encryption:** see section 2. Device API keys are
  never rendered back into any HTML form - editing a device leaves
  credential fields blank, and a blank submission means "keep the current
  value," matching the existing admin password-change pattern.

---
## 8. CI / Test Suite

- **Framework:** Pytest, with `PyYAML` now declared explicitly in
  `requirements.txt` - several tests parse `docker-compose.yml` directly
  and previously depended on PyYAML being present only as an incidental
  transitive dependency of an unrelated tool, which meant a genuinely clean
  `pip install -r requirements.txt` would fail to even collect 9 test
  files with `ModuleNotFoundError`. Verified fixed by testing from a fresh
  virtualenv with no other packages installed.
- **Current status, verified by an actual run, not assumed:** 137 passed,
  21 failed, out of 158 collected tests. All 21 failures are pre-existing
  and unrelated to the multi-device feature work - they fall into a few
  groups:
  - Missing root-level files this repo's own `SHA256SUMS` expects but that
    aren't present in this snapshot (`.gitignore`,
    `.env.example` before it was added back, `CHANGED-FILES.txt`, three
    other docs).
  - The `docker-compose.yml` secrets-wiring gap described in section 5.
  - A log-redaction assertion and a couple of ELK/TLS/network-segmentation
    assertions about details of the observability stack.
  - None of the 21 touch models, migrations, evaluation logic, or the
    device inventory/sync/assignment code added in this round of work.
- **New coverage added alongside the multi-device feature:**
  `tests/test_device_sync_service.py` (credential handling, error-message
  mapping, failure-status recording) and
  `tests/test_device_selection_authorization.py` (device selection can
  only ever resolve to a device already in the caller-supplied assigned
  list).

---
## 9. Deployment

- **Docker Compose:** `docker-compose.yml` defines `db` (Postgres),
  `migrate` (one-shot: `db upgrade && seed-defaults`), and `app`
  (Gunicorn). `docker-compose.elastic.yml` is a separate, optional stack
  for logging/observability - not required to run the app itself.
- **Environment configuration:** `.env.example` at the repo root documents
  every environment variable the application actually reads (verified by
  grepping every `os.getenv`/`read_secret` call, not copied from prior
  docs), grouped by concern: core secrets, database, networking, rate
  limiting, logging, the legacy standalone collector, and Compose.
- **First-time setup order:** create and `chown` the bind-mounted
  `uploads`/`static/uploads` directories (`data` needs no host-side setup -
  it's a named volume, section 7) then `docker compose up -d --build`, at
  which point `migrate` runs schema migrations and seeds defaults
  (including the backward-compat legacy device) before `app` starts.
- **Backup Strategy:** `scripts/postgres-backup.sh` /
  `postgres-restore.sh`, retention via `scripts/storage-retention.py`
  (single-device-data-dir limitation noted in section 3).

---
## 10. Known Gaps & Follow-Ups

Concrete, verified items - not speculative "future work":

1. **Synchronous device sync** could exceed Gunicorn's default 30s worker
   timeout against a FortiGate with a very large policy set; untested
   against real hardware so far, only against a mock API.
2. **`docker-compose.yml`'s app stack (`db`/`migrate`/`app`) doesn't use
   Docker secrets**, unlike the ELK stack which already does correctly;
   `.env` works but keeps values in the container's process environment.
3. **No `.gitignore` exists in this repository snapshot.**
4. **`auth/user_store.py` is orphaned dead code** with no remaining
   imports; `tests/test_no_legacy_user_store.py` expects it removed.
5. Several root-level files referenced by this repo's own `SHA256SUMS`
   manifest were absent from the snapshot this work was done against
   (`CHANGED-FILES.txt`, `COMPOSE-DEPLOYMENT.md`,
   `ELASTIC-STACK-IMPLEMENTATION-REPORT.md`, `ELK-SETUP.md`,
   `LOGGING-GUIDE.md` - present under `docs/` instead of the root in this
   snapshot). Worth confirming whether this is specific to how this
   snapshot was exported, or true of the actual working tree.

---
*Rewritten to reflect the multi-device inventory, per-device sync,
per-device evaluation work, the Policy Search/Catalog service, and the
Policy Risk Assessment service, and to replace prior claims that could not
be verified against the current codebase with claims that were - the test
counts, the SQLite pragma fix, the container UID pin, the PyYAML gap, and
the secrets-wiring comparison were all reproduced against a real run
described inline above, not asserted from memory.*
