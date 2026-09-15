---
name: architecture
description: Overview of Hirkanet's system architecture and components
metadata:
  type: reference
---

# Hirkanet System Architecture

**Repository:** `hirkanetcom`

Hirkanet is a Flask‑based web application that evaluates FortiGate firewall policy access requests. Below is a high‑level overview of its major components and how they interact.

---
## 1. Web Application Layer

- **Framework:** Flask (Python 3.12)
- **Entry point:** `main/routes.py` – defines the public web routes.
- **Gunicorn:** Production WSGI server configured via `gunicorn.conf.py`.
- **Authentication & Rate Limiting:**
  - `auth/` – forms, user store, rate‑limit implementation (`auth/rate_limit.py`).
  - Login rate‑limit settings are defined in `docs/LOGIN‑RATE‑LIMITING‑CHANGES.md` and applied via Flask‑Login.
- **Client API:** `client/` – wrappers for internal API calls used by the front‑end.
- **Admin UI:** `admin/` – admin CMS for managing users, services, and blog content.

---
## 2. Data Collection Layer

- **Collector:** `collectors/fortigate_collector.py`
  - Pulls configuration and policy data from FortiGate firewalls.
  - Stores atomic snapshots as JSON under `api/data/snapshots/`.
  - Snapshot format includes `addresses.json`, `interfaces.json`, `policies.json`, etc.

---
## 3. Evaluation Engine

- **Core:** `engine/evaluator.py`
  - Consumes the latest snapshot and applies heuristics to rank policies.
  - Uses helper modules:
    - `engine/cidr_tools.py` – CIDR parsing and IP‑range utilities.
    - `engine/interface_selector.py` – selects appropriate network interfaces.
  - Validation of input data performed by `engine/input_validation.py`.

---
## 4. Persistence Layer

- **Database:** PostgreSQL (SQLAlchemy ORM in `models.py`).
- **Migrations:** Alembic scripts in `migrations/versions/` handle schema evolution.
- **Backup/Restore:** Scripts in `scripts/` (`postgres-backup.sh`, `postgres-restore.sh`).
- **Secrets Management:** Sensitive values (passwords, keys) are stored in the `secrets/` directory. **⚠️ Critical:** These secrets have been exposed in the repo; they must be untracked and rotated (**see [[hirkanet-critical-secrets-exposed]]**).

---
## 5. Logging & Observability

- **Logging Configuration:** `logging_config.py` and `gunicorn_logging.py` define structured JSON logs.
- **ELK Stack:**
  - Docker Compose file `docker-compose.elastic.yml` spins up Elasticsearch, Logstash, Kibana, and Filebeat.
  - Logstash pipeline defined in `elk/logstash/pipeline/logstash.conf`.
  - Filebeat configuration in `elk/filebeat/filebeat.yml`.
  - TLS certificates are managed by helper scripts in `elk/` (e.g., `rotate-elastic-ca.sh`).
- **Guides:** See `docs/ELK-SETUP.md` and `docs/ELASTIC-STACK-IMPLEMENTATION-REPORT.md` for deployment details.

---
## 6. Security Controls

- **CSRF Protection:** Implemented in `security.py` and tested by `tests/test_csrf_protection.py`.
- **TLS/Hostname Verification:** Enforced via `docs/HTTPS-DEPLOYMENT.md` and validated by tests like `test_full_tls_hostname_verification.py`.
- **Rate Limiting:** Enforced on login endpoints (`docs/LOGIN‑RATE‑LIMITING‑CHANGES.md`).
- **Secret Rotation:** Required due to exposed plaintext secrets (see [[hirkanet-critical-secrets-exposed]]).

---
## 7. CI / Test Suite

- **Testing Framework:** Pytest with fixtures in `tests/`.
- **Key Tests:**
  - Container hardening, network segmentation, resource limits, TLS deployment, policy evaluation, secret configuration, etc.
- **Current Status:** The test suite is broken due to missing dependencies (`pytest`, `pyyaml`) and missing virtual‑env setup (**see [[hirkanet-test-suite-broken]]**).

---
## 8. Deployment

- **Docker Compose:** `docker-compose.yml` defines the Flask app, PostgreSQL, and the ELK stack.
- **Production Settings:** Gunicorn workers, log rotation, and database connection pooling are configured in `gunicorn.conf.py` and `logging_config.py`.
- **Backup Strategy:** Automated PostgreSQL backups using `scripts/postgres-backup.sh` and retention policies in `scripts/storage-retention.py`.

---
## 9. Future Work & Recommendations

1. **Remove plaintext secrets** from version control and rotate them.
2. **Fix the test suite** – add missing dependencies, ensure `requirements.txt` includes `pytest`, `pyyaml`, and any test helpers.
3. **Add health‑check endpoints** and container‑level security hardening (already covered by some tests).
4. **Document API contracts** in an OpenAPI spec for easier client integration.
5. **Implement CI pipelines** to run the full test suite on each push.

---
*This architecture overview was generated on 2026‑08‑19 based on the current codebase and documentation.*
