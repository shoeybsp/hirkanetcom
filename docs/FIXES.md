# Hirkanet Remediation Log

## 1. Correct Elastic ingestion container names

- Originally corrected Filebeat and Logstash to recognize the Hirkanet application and database containers.
- Fix #10 replaces exact container-name matching with the stable `hirkanet_log_role` Docker label.

Files changed:

- `elk/filebeat/filebeat.yml`
- `elk/logstash/pipeline/logstash.conf`
- `ELK-SETUP.md`

## Fix 2 — CSRF protection for state-changing forms

- Enabled global Flask-WTF `CSRFProtect` enforcement.
- Added CSRF tokens to all raw admin and client POST forms, including multipart uploads and destructive actions.
- Changed logout from GET/POST to POST-only and replaced logout links with CSRF-protected forms.
- Added a dedicated CSRF failure handler and user-facing HTTP 400 page.
- Added regression tests for token enforcement and template coverage.

## Fix 3 — Strict evaluator input validation

- Added a centralized validation and normalization layer in `engine/input_validation.py`.
- Requires at least one source and destination address.
- Accepts only known FortiGate address objects or valid IPv4 addresses/CIDRs.
- Rejects IPv6 until the evaluator's matching and proximity logic fully supports it.
- Accepts only known FortiGate services or validated port expressions.
- Enforces port range `1-65535`, ordered ranges, per-value length limits, deduplication, and per-field item limits.
- Applies the validation inside the evaluator itself as a defense-in-depth boundary.
- Applies identical validation to the interactive form and every CSV row.
- Rejects malformed CSV rows instead of silently skipping them and caps batch files at 1,000 data rows.
- Added focused validation regression tests and user-facing error pages.

## Fix 4 — Complete FortiGate IP-range support

- Preserves both endpoints of collected FortiGate `iprange` address objects.
- Adds a normalized inclusive range representation instead of converting ranges to their first host `/32`.
- Supports complete coverage checks for network-to-range, range-to-network, and range-to-range comparisons.
- Treats range boundaries as inclusive and requires the entire requested subnet or range to be covered.
- Uses the first range address only as a route-lookup representative, not as the range's matching semantics.
- Extends address proximity calculations to accept normalized range objects.
- Adds regression tests for boundaries, full coverage, overlap, direct IP evaluation, and named range requests.

## Fix 5 — Consistent Elastic TLS, ILM, and documentation

- Replaced the mixed secured/unsecured Elastic configuration with one private-CA TLS model.
- Added automatic CA and service-certificate generation in the `elastic_certs` Docker volume.
- Enabled Elasticsearch HTTPS and transport TLS.
- Enabled HTTPS for Kibana and certificate verification for its Elasticsearch connection.
- Enabled TLS between Filebeat and Logstash and HTTPS between Logstash and Elasticsearch.
- Aligned Filebeat with the shared `STACK_VERSION` used by the rest of the Elastic Stack.
- Made Elastic initialization create the Logstash role/user and invoke idempotent ILM provisioning automatically.
- Added the `hirkanet-logs-policy`, matching index template, initial `hirkanet-logs-000001` index, and `hirkanet-logs` write alias.
- Configured Logstash to write normal events through the ILM rollover alias.
- Implemented the documented dead-letter path for application JSON parse failures.
- Rewrote Elastic setup and logging documentation to match the deployed HTTPS endpoints, trust model, retention behavior, and certificate rotation procedure.

## Fix 6 — Centralized request validators

- Added a top-level `validation/` package for shared structured validation errors and reusable validators.
- Moved evaluator validation to `validation/evaluation.py`; retained `engine/input_validation.py` as a compatibility import.
- Centralized user, password, role, service, subscription-ID, and CSV-upload validation.
- Replaced duplicated checks in admin and client routes with typed validated results.
- Added strict identifier validation for subscriptions.
- Added upload content-signature checks so image extensions alone are not trusted.
- Added regression tests for the centralized validation layer.


## Fix 7 — Explicit heuristic-evaluation scope

- Added a clear product disclaimer that evaluator output is decision support, not authoritative FortiGate packet-flow simulation.
- Added persistent warnings to the single-request form, single-result view, and batch-result view.
- Renamed ambiguous UI labels such as “Best match” to “Top recommended candidate.”
- Documented material modeling limitations, including policy order, deny rules, NAT, schedules, identity, zones, policy routes, dynamic objects, VDOM context, and runtime reachability.
- Added an engine class docstring to prevent future integrations from representing rankings as definitive allow/deny decisions.
- Updated README and user-manual language to require firewall review, testing, change control, and rollback planning before implementation.

## Fix 8 — Shell-safe Elastic initialization JSON

- Escaped the JSON request bodies used to set the `kibana_system` password and create the `logstash_internal` user.
- Prevents Bash from stripping the JSON property-name quotes before the payload reaches Elasticsearch.
- Added a regression test that verifies both payloads remain valid shell-quoted JSON in the parsed Compose command.


## Fix 9 — File-based runtime secrets

- Replaced Compose-substituted passwords and encryption keys with read-only Docker secret files.
- PostgreSQL now uses `POSTGRES_PASSWORD_FILE`.
- Hirkanet reads `SECRET_KEY_FILE`, `POSTGRES_PASSWORD_FILE`, and `BOOTSTRAP_ADMIN_PASSWORD_FILE`.
- Elasticsearch uses `ELASTIC_PASSWORD_FILE`; Elastic initialization, Logstash, and Kibana load their credentials from `/run/secrets`.
- Database URLs are built safely with SQLAlchemy `URL.create`, avoiding reserved-character failures.
- Added `.env.example`, secret-file examples, secret documentation, and ignore rules that prevent real secrets from being committed.

## 10. Remove fixed Compose container names

- Removed every `container_name` declaration from `docker-compose.yml`.
- Added `hirkanet_log_role=application` and `hirkanet_log_role=database` labels to the services collected by Filebeat.
- Updated Filebeat filtering and Logstash application-log parsing to use those labels instead of exact runtime container names.
- This restores Compose project isolation, prevents cross-project name collisions, and allows services to be replicated without breaking log classification.

## Fix 11 — Functional Docker network segmentation

- Replaced the single shared bridge with three internal networks: `app-db`, `logging-ingest`, and `elastic-backend`.
- Limited the application and PostgreSQL to the database segment.
- Limited Filebeat to the logging-ingest segment and Kibana/Elasticsearch/init to the Elastic backend.
- Made Logstash the only dual-homed service because it must receive Beats traffic and deliver events to Elasticsearch.
- Disabled networking entirely for the certificate-generation setup container.

## Fix 12 — Harden the application container

- Runs the application container with a read-only root filesystem.
- Drops all Linux capabilities and prevents privilege escalation with `no-new-privileges`.
- Enables Compose's minimal init process for correct PID 1 signal and child-process handling.
- Limits the application to 256 processes and provides a small hardened `/tmp` tmpfs.
- Keeps only runtime data and general uploads writable through explicit mounts.
- Adds a 30-second graceful shutdown window for Gunicorn.
- Adds regression tests that prevent these hardening controls from being removed silently.

## Fix 13 — Docker resource limits

Added explicit CPU, memory, memory-reservation, and PID limits to every Compose service. Limits are sized by workload role and leave native-memory headroom above the Elasticsearch and Logstash JVM heaps. This prevents a single container from consuming all host resources while retaining enough capacity for startup and normal development workloads.

## Fix 14 — Service-aware health checks

- Replaced PostgreSQL's socket-only readiness probe with an authenticated `SELECT 1`.
- Changed Elasticsearch readiness to require a non-timed-out yellow or green cluster state over authenticated TLS.
- Enabled Logstash's local node API and verify that the `main` pipeline is loaded.
- Made Kibana readiness require the status API to report `available`.
- Replaced Filebeat's raw TCP-port probe with its native TLS-aware output test.
- Retained Hirkanet's database-backed `/readyz` application check and documented the separate `/livez` endpoint.
- Added regression tests preventing shallow `/dev/tcp` checks from returning.

## Fix 15 — Dead-letter ILM retention

- Added `hirkanet-dead-letter-policy` with rollover at 5 GB or 7 days and deletion after 30 days.
- Added `hirkanet-dead-letter-template`, initial index `hirkanet-dead-letter-000001`, and write alias `hirkanet-dead-letter`.
- Updated Logstash to write parse failures through the dead-letter ILM alias instead of unmanaged daily indices.
- Updated Elastic setup and logging documentation and added regression coverage.

## Fix 16 — Explicit HTTPS deployment for hirkanet.com

- Defined `https://hirkanet.com` as the canonical production origin.
- Added permanent HTTP-to-HTTPS and `www.hirkanet.com`-to-apex redirects in a supplied Nginx configuration.
- Kept Gunicorn loopback-bound and documented that port 5000 must not be publicly exposed.
- Added configurable Flask trusted-host validation and one-hop `ProxyFix` handling for trusted reverse-proxy headers.
- Documented DNS records, certificate issuance/renewal, HSTS sequencing, firewall exposure, secure-cookie behavior, and deployment verification.
- Added regression tests for the domain, proxy, and HTTPS deployment contract.


## Fix 17 — Explicit Elastic certificate rotation

- Retained the Elastic CA private key inside the protected certificate volume so service certificates can be renewed without changing the trust root.
- Changed certificate setup to fail closed when CA material is incomplete instead of deleting and recreating the CA.
- Reissues missing service certificates only with the existing CA.
- Added a guarded `elk/rotate-elastic-ca.sh --confirm-trust-root-rotation` workflow that records old/new CA fingerprints and requires deliberate trust redistribution.
- Documented CA backup, service-certificate renewal, trust-root rotation, and post-rotation verification.

## Fix 18 — Full TLS hostname verification

- Changed Filebeat-to-Logstash verification from CA-only `certificate` mode to `full` hostname verification.
- Added explicit `ssl_verification_mode => "full"` to both Logstash Elasticsearch outputs.
- Changed Kibana-to-Elasticsearch verification to `full`.
- Changed Elasticsearch transport verification to `full` for the generated DNS/IP SANs.
- Documented the required endpoint-to-certificate SAN mappings and fail-closed handling of hostname mismatches.
- Added regression tests preventing certificate-only or disabled verification from returning.

## Fix 19 — Split application and observability Compose projects

- `docker-compose.yml` now contains only Hirkanet and PostgreSQL.
- `docker-compose.elastic.yml` contains the Elastic certificate setup, Elasticsearch, initialization, Logstash, Kibana, and Filebeat.
- Removed Filebeat's cross-project `depends_on` relationship with the application.
- Kept log discovery through Docker metadata labels and host Docker log mounts; no shared network is required.
- Updated Elastic image references to the official `docker.elastic.co` registry.
- Added `COMPOSE-DEPLOYMENT.md` with independent startup, shutdown, validation, and cleanup commands.

## Fix 20 — Remove legacy JSON user store

- Removed `auth/user_store.py` and `data/users.json`.
- Removed package-level construction and exports of the file-backed `UserStore`.
- PostgreSQL/SQLAlchemy is now the only user identity, password-hash, and role store.
- Removed generated `__pycache__` and `.pyc` files from the source archive.
- Added regression tests that prevent the JSON identity store or its imports from being reintroduced.

## Fix 21 — Flask-Migrate/Alembic schema management

- Added Flask-Migrate and a version-controlled Alembic migration environment.
- Added a legacy-safe baseline revision that adopts existing `db.create_all()` databases without dropping data.
- Removed implicit table creation and seeding from normal application startup.
- Added a one-shot Compose `migrate` service; Gunicorn starts only after migration and idempotent seeding succeed.
- Added migration operations documentation and regression coverage.

## Fix 22 — Database-enforced foreign-key delete actions

- `subscriptions.user_id` and `subscriptions.service_id` now use `ON DELETE CASCADE`.
- SQLAlchemy relationships use `passive_deletes=True`; owned subscriptions also use `delete-orphan` cascade.
- Removed manual subscription cleanup from admin routes.
- Added Alembic revision `20260731_0002` to adopt the constraints on existing databases.

## Fix #23 — PostgreSQL backup and tested restore procedures

- Added custom-format PostgreSQL backup creation with SHA-256 manifests.
- Added mandatory-by-default disposable restore testing and schema checks.
- Added configurable retention while preserving a minimum number of recent backups.
- Added guarded restore tooling that refuses production replacement without explicit authorization.
- Added operational documentation for scheduling, off-host copies, recovery drills, and production restore.

## Fix 24 — Atomic, versioned FortiGate snapshots

- Replaced in-place JSON overwrites with immutable snapshot directories.
- Added atomic `data/current.json` publication.
- Added collection locking, staging cleanup, checksums, record counts, manifests, and retention.
- Made the evaluator load and verify one complete snapshot consistently.
- Added automatic evaluator reload when the active snapshot changes.
- Converted the bundled legacy flat dataset into an initial versioned snapshot.
- Added `FORTIGATE-SNAPSHOTS.md` and regression tests for atomicity, corruption detection, and retention.

## Fix 25 — Database indexes and check constraints

- Added database checks for valid user roles, nonblank service types, and valid subscription date ranges.
- Added a unique subscription constraint so a user cannot have duplicate rows for the same service.
- Added composite indexes matching active subscription and active service-type queries.
- Added Alembic revision `20260731_0003`, which fails closed when existing production rows violate a new invariant instead of rewriting data silently.
- Added regression coverage for model and migration definitions.

## Fix 26 — Centralized transaction rollback handling

- Added a shared SQLAlchemy transaction module for all application commits.
- Integrity and database failures now always rollback the scoped session before it can be reused.
- Added safe HTTP 409/500 handling for failed state-changing requests without exposing database details.
- Converted default data seeding into one atomic transaction, including explicit flush operations.
- Replaced direct route and login commits with the centralized transaction boundary.
- Added regression tests for commit, rollback, conflict, generic database failure, and direct-commit prevention.

## 27. Storage monitoring and retention policies

- Added read-only storage monitoring for host capacity, PostgreSQL size and volume usage, verified-backup freshness, FortiGate snapshots, and uploads.
- Added explicit dry-run-first retention for expired backup sets, abandoned partial files, superseded snapshots, and stale staging directories.
- Protected the active FortiGate snapshot from deletion.
- Kept uploaded media outside automatic deletion because references require application-aware review.
- Added configurable thresholds, exit codes suitable for alerting, scheduling guidance, and regression tests.
