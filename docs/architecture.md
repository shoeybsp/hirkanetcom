---
name: architecture
description: Overview of Hirkanet's system architecture and components
metadata:
  type: reference
  last_verified: 2026-10-10
---

# Hirkanet System Architecture

**Repository:** `hirkanetcom`

Hirkanet is a Flask web application for FortiGate firewall teams. It does four things:

1. **Evaluates access requests** (source, destination, service) against a collected copy of a device's policy configuration and ranks the existing policies that already cover, or could be extended to cover, the request.
2. **Catalogs policies**: browse, filter and inspect the collected policies.
3. **Scores policy risk**: ranks policies by security risk with remediation guidance.
4. **Audits DoS policies** live from the firewall.

It manages multiple registered devices. Each device has its own encrypted credentials, its own snapshot store, and its own set of authorized client users.

**How this document was verified.** It was rewritten from the current code (including the security and bug-fix patch from the October 2026 review) and the current `docker-compose.yml`, not carried over from the previous version. Anything that could not be confirmed from those sources is listed in [section 12](#12-known-gaps--follow-ups) under "Not verified".

---

## 1. System overview

```
Browser ──HTTPS──▶ reverse proxy (not in repo) ──▶ 127.0.0.1:5000
                                                       │
                                        ┌──────────────▼───────────────┐
                                        │ app container (gunicorn)     │
                                        │  Flask app  api/app.py       │
                                        │  ├─ admin_bp   /admin        │
                                        │  ├─ client_bp  /client       │
                                        │  └─ main_bp    /             │
                                        └───┬───────────┬──────────┬───┘
                                            │           │          │
                              SQLAlchemy    │   snapshot files     │ live REST (DoS pages only)
                                            ▼   (volume)           ▼
                              PostgreSQL (host)   /app/data      FortiGate API
                              users, services,    devices/<uuid>/   ▲
                              devices, ...        snapshots/...     │ collector (admin "Sync Now")
                                                                    │
                                                  collectors/ ──────┘
```

Key points:

- **One application process type.** There is no separate worker or scheduler. Collection runs inside the web request when an admin clicks "Sync Now".
- **Two data paths from the firewall.**
  - *Snapshot path*: the collector pulls policies, addresses, services, routes and interfaces into an immutable on-disk snapshot. The evaluator, catalog and risk assessor read only that snapshot.
  - *Live path*: the DoS policy pages call the FortiGate REST API directly on every request.
- **Database is external to the compose stack.** PostgreSQL runs on the Docker host and the containers reach it as `host.docker.internal`.

---

## 2. Web application layer

### 2.1 App factory and request pipeline (`api/app.py`)

`api/app.py` builds the Flask app at import time. In order:

1. `configure_logging()` runs before anything else, so import-time failures are structured too.
2. `APP_ENV` is read (default `development`). In production, `SECRET_KEY` is required, must be at least 32 characters, and must not contain placeholder markers. Otherwise startup raises.
3. Config is applied: `TRUSTED_HOSTS` (default `hirkanet.com,www.hirkanet.com,localhost,127.0.0.1`), `MAX_CONTENT_LENGTH` (`MAX_UPLOAD_BYTES`, default 5 MiB), CSRF token lifetime of 3600s, login rate-limit settings, and cookie flags (`HttpOnly`, `SameSite=Lax`, `Secure` only when `APP_ENV=production`).
4. `ProxyFix` (one hop for `X-Forwarded-For/Proto/Host/Port`) is installed **only** when `TRUST_PROXY_HEADERS` is true.
5. `init_db(app)` binds SQLAlchemy and retries the connection (10 attempts, 2s apart).
6. `CSRFProtect` is enabled globally, then request logging is installed, then `LoginManager`.
7. Blueprints `admin_bp`, `client_bp` and `main_bp` are registered.

### 2.2 Routes

**App-level (`api/app.py`)**

| Route | Method | Notes |
|---|---|---|
| `/login` | GET, POST | Rate limited per username and per IP. Redirects only to same-site path targets (see 9.3). |
| `/logout` | POST | CSRF protected. |
| `/livez` | GET | Always `200 {"status":"ok"}`. |
| `/readyz`, `/healthz` | GET | `SELECT 1`; `200 ready` or `503 not_ready`. `/healthz` is an alias kept for compatibility. |

**Error handlers.** `CSRFError` returns 400 (JSON when the client prefers JSON, otherwise `errors/400.html`). `DatabaseTransactionError` renders `errors/database_error.html` or JSON. 404 renders `errors/404.html`. Any other unhandled exception returns `{"error":"internal_server_error","request_id":...}` with status 500.

**CLI commands**

| Command | Purpose |
|---|---|
| `flask --app api.app db upgrade` | Apply Alembic migrations (Flask-Migrate). |
| `flask --app api.app seed-defaults` | Idempotent: bootstrap admin, the three default services, and the legacy default device. |
| `flask --app api.app cleanup-login-limits` | Delete expired failed-login rows. **Must be scheduled** (see 11.4). |

**Main (`main/routes.py`)**: `GET /` redirects based on login state and role.

**Admin (`admin_bp`, prefix `/admin`, all `@admin_required`)**

| Area | Routes |
|---|---|
| Dashboard | `GET /` shows counts of users, services, subscriptions, devices. |
| Users | list, create, edit, delete (POST), `subscriptions` editor |
| Services | list, create, edit, delete (POST) |
| Devices | list, create, edit, delete (POST), `POST /devices/<id>/sync`, `assignments` editor |
| Profile | `GET/POST /admin/profile` (change own password) |

**Client (`client_bp`, prefix `/client`, all `@login_required`)**

| Route | Method | Extra guard | Purpose |
|---|---|---|---|
| `/` | GET | | Dashboard with customizable widgets |
| `/dashboard/layout` | POST | | Save the widget layout |
| `/policy-evaluation` | GET | `policy_evaluation` (checked in the view; redirects to the dashboard with a message if missing) | Evaluation page |
| `/policy-evaluation/results` | POST | `policy_evaluation` | Single request evaluation |
| `/policy-evaluation/batch-results` | POST | `policy_evaluation` | CSV batch evaluation |
| `/policies` | GET | | Policy catalog page |
| `/policies/results` | GET, POST | | Filtered, paginated JSON |
| `/policies/<int:policy_id>` | GET | | Full policy JSON for the detail modal |
| `/risk-assessment` | GET | `policy_risk_assessment` | Risk page |
| `/risk-assessment/results` | GET, POST | `policy_risk_assessment` | Scored, filtered JSON plus summary |
| `/dos-policies` | GET | `dos_policy` | DoS page |
| `/dos-policies/results` | GET | `dos_policy` | Live list from the firewall |
| `/dos-policies/audit` | GET | `dos_policy` | Live audit with scores |
| `/dos-policies/<int:policy_id>` | GET | `dos_policy` | Single DoS policy |

The policy catalog and policy detail routes are gated by device assignment only, not by a service subscription.

### 2.3 Authentication and sessions

- Flask-Login with cookie sessions. There is no server-side session store.
- Passwords use scrypt (`security.py`). Legacy salted-SHA-256 hashes still verify and are upgraded to scrypt on next successful login.
- `verify_password` is also run against a dummy hash when the username does not exist, to equalize response time.
- Roles are `admin` and `client` (`ck_users_role` check constraint).
- Sessions are **not** invalidated by password change, role change or admin reset (see 12).

### 2.4 Authorization (`client/access.py`)

- `subscription_required(service_type)` checks for an active `Subscription` to an active `Service` of that type. A subscription whose `end_date` has passed is treated as inactive.
- `get_assigned_devices(user_id)` returns the user's active assignments to active devices.
- `has_device_access(user_id, device_id)` is re-checked in every JSON route that takes a `device_id`; clients can never address a device they are not assigned.
- Unauthenticated requests are redirected to `/login` by Flask-Login. Missing subscription or device access on JSON routes yields 403.

---

## 3. Device inventory and multi-device support

### 3.1 Data model

`Device` (`devices` table):

- Connection: `api_host`, `api_scheme`, `vdom`, `verify_ssl`, `timeout_seconds`, `skip_monitor_routes`, `keep_snapshots`.
- Credentials (Fernet-encrypted): `api_key_encrypted` (used today); `auth_username_encrypted` and `auth_password_encrypted` (stored for future device types, not read by any code today).
- Storage: `data_dir` (unique), the path of this device's snapshot store.
- State: `is_active`, `created_at`, `updated_at`, and the sync result fields `last_sync_at`, `last_sync_status` (`success` or `failure`), `last_sync_message`, `last_snapshot_id`.
- Check constraints: `device_type IN ('fortigate')`, and `last_sync_status` null or one of the two values.

`DeviceAssignment` grants a client user access to a device (unique per user and device, with `is_active`).

### 3.2 Admin workflow

- **Create/edit device** validates input (`validation/admin.py`). `api_host` must be a hostname or IP with an optional port, optionally prefixed with `http://` or `https://`. Paths, query strings, fragments and embedded credentials are rejected. A new device gets `data_dir = data/devices/<uuid>`. The API key is encrypted before it is stored and is never rendered back.
- **Sync Now** runs the collector for that device synchronously (section 4).
- **Assignments** replace the device's assigned set (only users with role `client` are selectable).
- Admin create, update and delete actions emit structured audit events (section 8).

### 3.3 Credential encryption (`secret_crypto.py`)

Secrets are encrypted with Fernet. The key is derived as `SHA-256(DEVICE_CREDENTIAL_KEY)`. In production the key must be at least 32 characters and must not look like a placeholder. Outside production a hardcoded development key is used if the variable is unset. Decrypt failures raise `CredentialEncryptionError` and surface as a short, sanitized message.

---

## 4. Data collection layer

### 4.1 Collector (`collectors/fortigate_collector.py`)

Pulls from the FortiGate REST API v2 using a Bearer token:

| Output file | Source endpoints |
|---|---|
| `policies.json` | `cmdb/firewall/policy` |
| `addresses.json` | `cmdb/firewall/address`, `cmdb/firewall/addrgrp` |
| `services.json` | `cmdb/firewall.service/custom`, `cmdb/firewall.service/group` |
| `interfaces.json` | `cmdb/system/interface` |
| `routes.json` | `cmdb/router/static`, plus `monitor/router/ipv4` unless `skip_monitor_routes` is set |

Objects are normalized before writing (address and service shapes, route network and interface keys).

### 4.2 Snapshot layout and publishing

```
<data_dir>/
├── current.json                  # pointer to the active snapshot
└── snapshots/
    └── <snapshot_id>/
        ├── policies.json  addresses.json  services.json
        ├── routes.json    interfaces.json
        └── manifest.json         # SHA-256 per file, source metadata
```

`publish_snapshot` writes into a staging directory, fsyncs files and directories, then swaps the pointer atomically, so readers never see a half-written snapshot. Old snapshots beyond `keep_snapshots` are pruned.

An exclusive non-blocking `flock` (`collector_lock`) on the output directory prevents two syncs of the same device from running at once.

### 4.3 Snapshot reading (`engine/snapshot_store.py`)

`resolve_active_snapshot` follows `current.json`, rejects any pointer that resolves outside the `snapshots/` directory, and `verify_snapshot` checks every file against the manifest's SHA-256 before the data is used. A missing, corrupt or tampered snapshot raises `SnapshotError`.

### 4.4 Sync service (`collectors/sync_service.py`)

`run_device_sync(device)` builds collector arguments from the `Device` row (decrypting the key), runs the collector under the lock, and updates the `last_sync_*` fields on both success and failure. Error text shown to the admin is shortened and sanitized (`DeviceSyncError`). The HTTP session retries transient failures.

---

## 5. Evaluation engine (`engine/evaluator.py`, class `SecureTrackLite`)

The evaluator is a **heuristic candidate ranker**. It does not reproduce FortiGate packet processing and must not be used as an authoritative allow/deny decision. This is stated in the class docstring and in the UI disclaimer.

**Inputs.** Lists of sources, destinations and services, each validated first by `validation/evaluation.py`. Each list is limited to 50 items, each value to 128 characters, and a CSV batch to 1000 rows. Addresses may be a host IP, a CIDR, an `a.b.c.d-e.f.g.h` range, or an address-object name.

**Matching.**

- Address objects, groups and ranges are expanded (`_expand_address_names`). CIDR arithmetic is in `engine/cidr_tools.py` (`to_network`, `to_range`, `is_subset`, `any_overlap`, `is_covered_by`).
- Ingress and egress interfaces are inferred from the collected routes by longest-prefix match (`engine/interface_selector.py`).
- Services match by name, by alias (`tcp-443`, `443`, `tcp-8000-8080`) and through service groups. A multi-entry `tcp-portrange` such as `"80 443 8000-8080"` is split into entries, and a source-port suffix (`443:1024-65535`) is ignored. The predefined `ALL` service (protocol IP, protocol number 0, no ports) matches any requested service. A `protocol IP` service with a non-zero protocol number is **not** a wildcard.

**Scoring** (heuristic): roughly +40 for source coverage, +40 for destination coverage and +20 for service coverage, with proximity bonuses for tighter address matches; interface alignment is also considered. Penalties apply for unmatched extra objects (capped at 10 per side and 5 for services), for using the `all` address object (−15 per side) and for each broad network (−15 per object). Each result carries a score and a `candidate_action`, for example `already covered` or `add <missing items>`.

**Caching.** `client/routes.py` keeps one `SecureTrackLite` per device in a per-worker dictionary and rebuilds it when the active snapshot ID changes.

**Batch mode.** `POST /client/policy-evaluation/batch-results` accepts a UTF-8 `.csv` of at most 2 MiB (`validation/uploads.py`) and validates every row up front. If any row is invalid, no evaluation runs and the request renders `client/batch_validation_error.html` listing the first 50 errors with a count of the rest. Otherwise it renders the batch results page.

---

## 5b. Policy search / catalog (`services/policy_search.py`)

`PolicySearchService` loads the active snapshot for a device and filters it in memory. String filters are case-insensitive substring matches on `name`, `action`, `status`, `service`, `srcaddr`, `dstaddr`, `srcintf`, `dstintf` and `logtraffic`. Results are sorted by `policyid`, `name` or `action` and paginated (`limit` default 100, plus `offset`). `get_policy_by_id` backs the detail modal.

## 5c. Policy risk assessment (`engine/risk_assessor.py`, `services/risk_assessment.py`)

`PolicyRiskAssessor` scores each policy on four dimensions and combines them with fixed weights:

| Dimension | Weight | Examples of what raises the score |
|---|---|---|
| `address_scope` | 0.35 | source or destination is any (`0.0.0.0/0`), very broad networks |
| `logging` | 0.25 | traffic logging disabled, UTM-only logging with UTM features disabled, deny rules with logging disabled |
| `config` | 0.25 | source or destination interface set to ANY (+25 each), non-default schedule, disabled status, more than 10 service objects |
| `staleness` | 0.15 | disabled policies, deny rules with no logging |

Levels: `critical` ≥ 80, `high` ≥ 60, `medium` ≥ 40, `low` ≥ 20, otherwise `info`. Each result lists findings and remediation text per dimension. `RiskAssessmentService.get_assessment` filters by `risk_level`, `dimension`, `min_score` and `name`, sorts, paginates, and returns a summary of level counts alongside the page. There is no separate per-policy risk detail route; the results JSON carries the findings.

Note: `staleness` is derived only from status and logging; it does not use hit counts or timestamps, which the collector does not gather.

## 5d. DoS policy service (`services/dos_policy.py`, `engine/dos_policy_auditor.py`)

This feature is **live and read-only**, unlike the snapshot-based services.

- `DosPolicyService(device)` builds a `FortiGateClient` (`engine/fortigate_client.py`) from the device row, with the decrypted key and the device's TLS and timeout settings. Methods: `list_policies`, `get_policy`, `audit_policies`, `close`. All FortiGate calls are GETs against `/api/v2/cmdb/firewall/DoS-policy`.
- `DosPolicyAuditor` scores each policy on five weighted dimensions: anomaly coverage (0.30), threshold configuration (0.25), logging (0.20), policy scope (0.15) and action (0.10). Critical anomalies that should always be enabled are `tcp_syn_flood`, `icmp_flood`, `udp_flood`, `tcp_udp_flood`, `ip_spoofing` and `land_attack`. Risk levels use the same thresholds as section 5c.
- Validation lives in `validation/dos_policy.py`.
- There is no snapshot and no caching: **each page load makes live calls to the firewall.** See 12 for the consequence.

---

## 6. Client dashboard and UI

### 6.1 Dashboard widgets (`client/dashboard_widgets.py`)

The client home page is a set of widgets: one **policy catalog** card plus one card per subscribed service. `SERVICE_WIDGETS` maps each known `service_type` (`policy_evaluation`, `policy_risk_assessment`, `dos_policy`) to an endpoint, icon, description and call-to-action. A service type with no page renders as a "Coming Soon" card.

Each user's layout is stored as a JSON list of widget keys in `users.dashboard_layout`. A null value means "never customized: show everything". Stored layouts are never trusted: keys are re-validated against the widgets the user is currently entitled to, so removing a subscription removes the card.

### 6.2 Templates and branding

- Server-rendered Jinja templates with Bootstrap CSS (`static/bootstrap.min.css`) and the app stylesheet (`static/style.css`).
- Branding assets are in `static/img/` (`hirkanet-logo.png`, `hirkanet-mark.png`, `favicon-32.png`, `apple-touch-icon.png`) plus `static/favicon.ico`. `templates/_brand_head.html` is the shared favicon include, used by the admin and client base templates, the error pages and the login page.
- `templates/login.html` is a self-contained split-screen page (brand hero on the left, form on the right). It uses a CSS gradient styled in the logo's colors, not the logo image as a full-page background. Its styles are inline in the template.
- Interactive pages (catalog, risk, DoS, evaluation) fetch JSON and build tables in JavaScript.

### 6.3 Escaping convention

Every string that originates from the firewall (policy, address, service and interface names, IDs and other fields) is HTML-escaped (`escapeHtml` / `escHtml`) before it is concatenated into `innerHTML`, and numeric IDs placed in inline handlers are coerced with `Number()`. New front-end code must follow the same rule. Jinja autoescape is on for server-rendered output.

---

## 7. Persistence layer

### 7.1 Database selection (`db_url.py`)

Resolution order: `DATABASE_URL`, then `POSTGRES_*` variables (when `POSTGRES_HOST` is set; `POSTGRES_PASSWORD` is required), then a local SQLite file `fortigate_policy.db` in the repo directory as a development fallback. SQLite connections enable `PRAGMA foreign_keys=ON`.

### 7.2 Tables

| Table | Purpose |
|---|---|
| `users` | Accounts: username (unique), password hash, role, `dashboard_layout` |
| `login_rate_limits` | Shared failed-login counters (HMAC-hashed identifiers, scope `username` or `ip`, window and block timestamps) |
| `services` | Subscribable features (`policy_evaluation`, `policy_risk_assessment`, `dos_policy`) |
| `subscriptions` | User-to-service grants with `is_active`, `start_date`, optional `end_date` |
| `devices` | Registered firewalls (section 3.1) |
| `device_assignments` | Client-to-device grants |

Foreign keys cascade on delete, with indexes and check constraints on the hot paths. Timestamps are stored without time zone; Python writes UTC.

### 7.3 Migrations (`migrations/versions/`)

| Revision | Change |
|---|---|
| 0001 | Initial schema |
| 0002 | Foreign key delete actions |
| 0003 | Indexes and check constraints |
| 0004 | `login_rate_limits` |
| 0005 | `devices` and `device_assignments` |
| 0006 | API keys table (later dropped) |
| 0007 | Drop API keys |
| 0008 | Drop blog tables |
| 0009 | `users.dashboard_layout` |

### 7.4 Seeding (`seed-defaults`)

Idempotent and run on every `compose up` after migrations:

1. Creates the bootstrap admin from `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` if both are set (password at least 12 characters) and the user does not exist.
2. Ensures the three default services exist.
3. Creates a "Default FortiGate" device with `data_dir="data"` **only when the devices table is empty**. This means deleting every device brings that blank device back at the next deploy.

### 7.5 Filesystem

Snapshots live under `/app/data` (the `hirkanet_data` volume). Per-device stores are `data/devices/<uuid>/`; the legacy single-device layout is `data/`.

---

## 8. Logging and observability

- **Format.** `logging_config.py` emits JSON lines with `@timestamp`, level, message, `event.dataset` and extra fields, shaped for Elastic. `LOG_FORMAT=json` also switches Gunicorn's access log to the JSON logger (`gunicorn_logging.py`). `LOG_LEVEL` controls both.
- **Redaction.** Sensitive keys are masked (`password`, `token`, `authorization`, `cookie`, `secret`, `csrf_token`, `api_key`, and so on), both when nested in a value and when passed as a top-level `extra` field.
- **Request logging.** Every request gets an `X-Request-ID`. A client-supplied ID is accepted only if it matches `[A-Za-z0-9._-]{1,64}`; otherwise a UUID is generated. The ID is echoed in the response header, logged with the request, and included in 500 responses. The hooks tolerate requests that CSRF aborts before the logger starts.
- **Event types** include `authentication_success`, `authentication_failure`, `authentication_rate_limited`, `logout`, `csrf_validation_failure`, `subscription_authorization_denied`, `policy_evaluation_device_denied`, `policy_evaluation_started/completed/validation_failure`, `policy_evaluation_batch_completed/validation_failure`, `device_sync_requested`, `database_operation_failure`, `readiness_failure`, `unhandled_exception` and `application_start`. Admin audit events are `audit_user_created/updated/deleted`, `audit_password_changed`, `audit_service_deleted`, `audit_subscriptions_updated`, `audit_device_created/updated/deleted` and `audit_device_assignments_updated`, each carrying the actor and target identifiers.
- **Shipping.** The `app` container carries the label `hirkanet_log_role: application` for Filebeat autodiscovery. Docker's `json-file` driver rotates at 10 MB × 5 files. The `elk/` directory holds the Filebeat and Logstash configuration and certificate and ILM helper scripts.
- **Health.** `/livez` for liveness, `/readyz` for readiness (database reachable). The compose healthcheck calls `/readyz`.

---

## 9. Security controls

### 9.1 Secrets

- `SECRET_KEY` and `DEVICE_CREDENTIAL_KEY` are read through `read_secret`, which supports a plain variable or a `*_FILE` path (Docker or Kubernetes secrets).
- In production both must be at least 32 characters and must not contain placeholder markers (`change-me`, `development-only`, `replace-me`, `example`). Otherwise the app refuses to start.
- Outside production, a development fallback exists. This is why `APP_ENV` must be set explicitly in any real deployment (see 12).

### 9.2 Passwords and accounts

scrypt hashing; 12-character minimum when creating users; failed-login rate limiting; the last administrator cannot be deleted or demoted.

### 9.3 Login protections

- **Rate limiting** (`auth/rate_limit.py`): counters per username (default 5 failures) and per source IP (default 20) within a window (default 900s), then a block (default 900s). Identifiers are HMAC-hashed with the secret key, and state is in the database so it is shared across workers.
- **Redirect safety**: `next` is followed only for a path that starts with a single `/`, with no backslash, control characters, scheme or host.
- **Timing**: unknown usernames incur a comparable hashing cost.

### 9.4 Web protections

Global CSRF (including logout), `TRUSTED_HOSTS` allow-list, `HttpOnly`/`SameSite=Lax` cookies, `Secure` cookies in production, upload limits (`MAX_UPLOAD_BYTES`; CSV 2 MiB, UTF-8 only, 1000 rows), strict input validation modules (`validation/`) on every route that takes user input.

### 9.5 Device access

Every client route re-checks device assignment and subscription server-side. `api_host` is validated as host and port only. Credentials are encrypted at rest and never returned to the browser. Snapshot reads verify checksums and pointer containment.

### 9.6 Container hardening

Non-root user (UID 10001), read-only root filesystem, all capabilities dropped, `no-new-privileges`, `noexec` tmpfs, CPU, memory and PID limits, port published on loopback only.

---

## 10. Test suite

`tests/` contains unit and integration tests for validation, evaluator logic, risk and DoS scoring, access control, rate limiting, logging, migrations, snapshot handling, CSRF and the new review fixes (`test_review_fixes.py`, `test_evaluator_service_matching.py`).

Last recorded run (after the review patch): **221 passed, 24 failed** (25 failed before the patch). Run with `python -m pytest -q`.

The remaining failures are not application logic bugs. They are tests that assert on repository files or content that has since changed or moved (deleted legacy files, constraint names, template paths, deployment and documentation files). Triage them as fix, update or delete; see 12.

---

## 11. Deployment

### 11.1 Compose stack (`docker-compose.yml`, project name `hirkanet-app`)

| Service | Role |
|---|---|
| `migrate` | One-shot (`restart: "no"`). Waits up to 60 s for PostgreSQL at `host.docker.internal`, then runs `flask db upgrade && flask seed-defaults`. Limits: 0.5 CPU, 384 MB. |
| `app` | Gunicorn serving `api.app:app`. Starts only after `migrate` completes successfully. Limits: 0.75 CPU, 512 MB, 256 PIDs. Healthcheck on `/readyz` (15 s interval, 30 s start period). `init: true`, 30 s stop grace. |

Both services use `env_file: .env`, a bridge network `frontend`, and `extra_hosts: host.docker.internal:host-gateway`.

**Not in the stack:** PostgreSQL, a TLS-terminating reverse proxy, and the Elastic stack. The app binds `127.0.0.1:5000`, so a proxy on the host must front it. When it does, set `TRUST_PROXY_HEADERS=true` so client IPs and the scheme are correct. The `migrate` service forces it to `false`.

**Volumes**

| Mount | Purpose |
|---|---|
| `hirkanet_data` → `/app/data` | Snapshot stores. Named volume, owned by UID 10001. |
| `./uploads` → `/app/uploads` | Bind mount; no application code writes here today |
| `./static/uploads` → `/app/static/uploads` | Bind mount; same |

### 11.2 Image (`Dockerfile`)

`python:3.12-slim`, non-root user `app` (UID/GID 10001), dependencies from `requirements.txt`, `CMD gunicorn --config gunicorn.conf.py api.app:app`.

### 11.3 Gunicorn (`gunicorn.conf.py`)

Binds `0.0.0.0:5000`; access and error logs to stdout and stderr; level from `LOG_LEVEL`; JSON access logs when `LOG_FORMAT=json`. **It sets no `workers`, `threads` or `timeout`**, so Gunicorn's defaults apply: one synchronous worker and a 30-second timeout.

### 11.4 Configuration reference

| Variable | Purpose |
|---|---|
| `APP_ENV` | `production` enables secure cookies and strict secret checks; default `development` |
| `SECRET_KEY`, `DEVICE_CREDENTIAL_KEY` | Required in production, at least 32 characters, no placeholders |
| `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_PASSWORD` | First admin (password at least 12 characters) |
| `DATABASE_URL`, or `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | Database connection |
| `TRUSTED_HOSTS` | Comma-separated allowed `Host` values |
| `TRUST_PROXY_HEADERS` | Honor `X-Forwarded-*` from exactly one proxy hop |
| `MAX_UPLOAD_BYTES` | Request body limit (default 5 MiB) |
| `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS`, `_IP_ATTEMPTS`, `_WINDOW_SECONDS`, `_BLOCK_SECONDS`, `_RETENTION_SECONDS` | Lockout tuning |
| `LOG_LEVEL`, `LOG_FORMAT`, `SERVICE_NAME` | Logging |
| `FORTIGATE_*` | Defaults for the stand-alone collector CLI (`collectors/fortigate_collector.py`); the web app uses per-device settings instead |

The sample file in the repository is named `env.example`.

### 11.5 Operations

- **Scheduled jobs (host cron or similar):**
  - `flask --app api.app cleanup-login-limits`, daily.
  - `scripts/storage-retention.py`, which prunes old snapshots under both `data/snapshots` and every `data/devices/<id>/snapshots`.
  - `scripts/storage-monitor.py`, a per-device capacity, freshness and pointer-integrity report that also measures upload directories.
- **Backups:** `scripts/postgres-backup.sh`, `postgres-restore.sh` and `postgres-restore-test.sh`. Snapshot data in `hirkanet_data` is reproducible by re-syncing, so it is lower priority than the database.
- **Other scripts:** `scripts/audit_artifact_distribution.py` fingerprints sensitive archives and images and finds duplicate copies.

---

## 12. Known gaps and follow-ups

Severity ratings are for a pilot with real devices. Items marked **(review)** come from the October 2026 code review; the fixed ones are described in section 9 and not repeated here.

**Security**

1. **TLS verification is off by default.** `Device.verify_ssl` defaults to false, as do the client and collector defaults, so the API token travels over unverified TLS. Needs a safe default plus a per-device CA bundle or pinned fingerprint field. **(review, high)**
2. **No session invalidation.** Password change, role change and admin reset leave existing cookies valid. Fix with a `User.session_version` checked in `load_user`. **(review, medium)**
3. **`APP_ENV` fails open.** When unset, the app runs with development behavior (insecure cookies, fallback keys). Treat unset as production, or require an explicit `development`. **(review, medium)**
4. **No security headers or CSP.** Inline scripts, inline styles and inline `onclick` handlers in templates block a strict CSP. **(review)**
5. **Lockout can be abused** to lock out a known username for the block period. Consider keying on username plus IP and using progressive delay. **(review, low)**
6. **No MFA, no disabled-user flag, no forced password change** for the bootstrap admin.
7. `auth_username_encrypted` and `auth_password_encrypted` are stored but unused. The encryption key is a plain SHA-256 of the configured string with no rotation; moving to `MultiFernet` would allow key rotation.

**Reliability and performance**

8. **Gunicorn runs one sync worker with a 30 s timeout.** The DoS pages call the firewall live, and the HTTP client retries up to 3 times with a 30 s timeout each. One slow firewall can block every user and trigger worker kills. Set `workers`, `threads` and `timeout` explicitly, cache DoS responses for 10 to 30 s per device, and consider moving sync to a background job. **(review, medium)**
9. **Sync holds a web request and a database transaction open** while talking to the firewall. No scheduled sync exists; clients depend on an admin clicking Sync Now.
10. **The per-worker engine cache** is never evicted. Deleted devices stay in memory, and with more than one worker each worker holds its own copy. **(review, low)**
11. The catalog and risk services reload and checksum the full snapshot on every request; the evaluator caches but they do not. **(review, low)**
12. `seed-defaults` re-creates the blank "Default FortiGate" device whenever the devices table is empty. **(review, low)**

**Deployment**

13. **The `migrate` readiness probe hardcodes `host.docker.internal`** and `POSTGRES_PORT`, while the app resolves its database from `DATABASE_URL` or `POSTGRES_HOST`. If `.env` points elsewhere, the probe waits on the wrong host. Make it use the same resolver.
14. `./uploads` and `./static/uploads` are mounted but nothing in the application writes to them. Remove the mounts or document the intent.
15. No reverse proxy or TLS termination is part of the stack. `SESSION_COOKIE_SECURE` makes HTTPS mandatory in production.

**Repository hygiene**

16. `fortigate_policy.db` (a populated SQLite file) and `__pycache__` directories are in the source tree; ignore `*.db`.
17. `.gitignore` ignores `.env.example`, but the sample file is named `env.example`. Rename one or the other.
18. **Dead code to delete:** `auth/user_store.py`, `templates/client/dos_policy_form.html`, `engine/input_validation.py` (a compatibility shim), the unused `ChangePasswordForm` in `auth/forms.py` (its 4-character minimum contradicts the 12-character policy), and the duplicate `templates/batch_results.html` / `templates/results.html` pair. `pytest` should not be in the production `requirements.txt`.
19. `elk/filebeat/filebeat.yml.bak` and the root `SHA256SUMS` look like leftovers.
20. Fix, update or delete the 24 stale tests so a green run is meaningful.

**Design**

21. `client/routes.py` is about 950 lines and repeats the "resolve device, check access, build service, return JSON" sequence in several routes with slightly different status codes. Extract a shared helper and split by feature.
22. Time handling mixes timezone-aware defaults with naive columns. Pick one convention.
23. The scoring weights in the evaluator and risk assessor are heuristic constants. Name them, test them and show the breakdown in the UI.

**Not verified in this rewrite**

The sources available for this rewrite did not include `README.md`, the `docs/` directory, a `docker-compose.elastic.yml`, or the `.env` actually used in deployment. Statements about the Elastic stack in section 8 are based on the files in `elk/` only. If those exist in your full repository, check them against sections 8 and 11.
