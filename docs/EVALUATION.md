# Hirkanet — Project Evaluation (2026-08-10)

A **FortiGate firewall policy evaluation web app**: Flask + SQLAlchemy/Postgres + Gunicorn behind a reverse proxy, with a REST collector that pulls firewall policies/addresses/routes into versioned JSON snapshots, a heuristic candidate-ranking engine, a subscription-based client portal, admin CMS (users/services/blog), and a full ELK observability stack.

## Overall assessment

Good, security-conscious, actively hardened project — but a **serious secret-hygiene problem** undermines some of that effort, and the **test suite cannot currently run** (unverified "green" state).

Engineering quality is well above typical: structured logging with redaction, centralized transaction rollback, strict input validation, DB-backed rate limiting, atomic snapshot storage with checksums, container hardening, and a real remediation log. See the priority-ordered issues below.

---

## 🔴 Critical

### 1. Real secrets are committed to git — in plaintext
Every extensionless file in `secrets/` is **git-tracked** (introduced in commit `a353391`, present on `main` and `origin/main`):
- `secrets/flask_secret_key`, `postgres_password`, `elastic_password`, `kibana_password`, `logstash_password`, `bootstrap_admin_password`, and the 3 Kibana encryption keys all contain **real 64-char hex values** (they differ from their `.example` placeholders; e.g. `flask_secret_key` = `57959a39…`).
- These are live secrets, not placeholders — the `.example` files are the placeholders.
- `.env` (real, untracked) does **not** match the tracked secret files (`SECRET_KEY` differs), so the two systems are already out of sync.

`.env.example` says *"Never commit the real .env file to Git"* — but the same policy was not applied to `secrets/`. Anyone with repo access (now and in all future clones/forks) gets Postgres, Elasticsearch, Kibana, Logstash, and admin credentials.

**Remediation:** (1) add `secrets/*` (minus `*.example`) to `.gitignore`; (2) `git rm --cached` the tracked secret files; (3) **rotate every one of these secrets** plus the `FORTIGATE_TOKEN` — history is public and `git filter-repo`/BFG cannot un-publish what is already cloned; (4) consider Docker secrets or a `.env`-only approach to avoid recurrence.

---

## 🟠 High

### 2. `data/users.json` is committed and appears to be the legacy user store
Git-tracked (committed in `bcaf637`, first commit). The app and `tests/test_no_legacy_user_store.py` have moved to the DB-backed `User` model, yet `auth/user_store.py` still exists as dead code. Verify `users.json` contains no real user data; if so, remove from repo and delete `auth/user_store.py` + `data/users.json`.

### 3. The test suite cannot run
`python3 -m pytest` fails (`No module named pytest`); the environment's pip is externally managed (PEP 668 — needs a venv). `requirements.txt` is missing `pyyaml`, which several compose/HTTPS tests `import yaml` and would need. **Tests were not executed during this evaluation.** At least one test targets a nonexistent file: `tests/test_https_deployment.py:34` reads `deployment/nginx/hirkanet.conf`, but there is no `deployment/` directory in the repo — that test (and the nginx TLS deployment it asserts) is currently impossible to satisfy. Either add the nginx config + `HTTPS-DEPLOYMENT.md` assets or drop/repurpose the test.

### 4. Filebeat is pinned to an outdated, mismatched version
`docker-compose.elastic.yml` runs Elasticsearch/Logstash/Kibana at `9.3.8` (`STACK_VERSION`) but `filebeat` is pinned at `elastic/filebeat:8.19.19` — a **major version behind** (8.x vs 9.x) and hardcoded while the rest uses the env var. Violates the project's own "keep all four on exactly the same version" convention; risks ingestion/beats-registry incompatibilities.

### 5. FortiGate token is weak
`.env` has `FORTIGATE_TOKEN=ae3a2f4a5f` — **10 chars**, not the 32+ hex the file recommends, and short for a firewall API credential.

---

## 🟡 Medium

### 6. `TRUSTED_HOSTS` / host-header handling
`api/app.py:31-35` defaults `TRUSTED_HOSTS` to a fixed list and sets `PREFERRED_URL_SCHEME="https"` in production. No `SERVER_NAME` and no explicit host-verification error handler — protection relies on `TRUSTED_HOSTS` being set via env in the real deployment (the compose file does set it; confirm).

### 7. Dead/legacy code remains
- `auth/user_store.py` (JSON `UserStore`) is orphaned — `tests/test_no_legacy_user_store.py` asserts it's gone, but the file is still there.
- `engine/input_validation.py` is a re-export shim of `validation/evaluation.py` (fine, but noted).

### 8. Login failure path
Non-enumerating flash message on failed login is good; the rate-limit/429 path exposes `Retry-After` and scope — acceptable but worth double-checking username-enumeration timing surfaces (mitigated by shared rate-limit + hash path).

---

## 🟢 Strengths

- **Security posture genuinely thoughtful**: scrypt hashing with transparent legacy-SHA256 migration; global CSRFProtect; `SESSION_COOKIE_HTTPONLY/SECURE/SAMESITE`; ProxyFix gated behind env flag; DB-backed login rate limiting with **HMAC-hashed identifiers**; subscription-based authorization (403 + audit log); strict input validation (ports 1–65535, ordered ranges, IPv4-only, dedupe, 1000-row batch cap); image signature + extension checks on uploads.
- **Container hardening**: `read_only`, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, resource limits, loopback-only binding, healthchecks, tmpfs.
- **Atomic, versioned FortiGate snapshots** with SHA-256 manifests, staging dirs, `fsync`, pointer-swap, lock file, pruning.
- **Centralized transaction handling** (`database_transactions.py`) with guaranteed rollback and typed errors → clean HTTP responses.
- **Structured JSON logging** with field redaction and request-ID correlation, wired into gunicorn + ELK.
- **22+ documented remediation fixes** (`docs/FIXES.md`); strong test coverage *intent* (32 test files for compose hardening, ELK, TLS, rate limiting, migrations, snapshots, rollback).
- **Flask-Migrate/Alembic** with down-grades, check constraints, composite indexes.

---

## Priority order

1. **Untrack + rotate** all committed secrets (`secrets/*`, check `data/users.json`), update `.gitignore`, align `secrets/` with `.env`.
2. **Get the test suite runnable**: add `pyyaml` to `requirements.txt`, document venv setup, fix or remove the `deployment/nginx/hirkanet.conf` test/asset.
3. **Pin Filebeat to `9.3.8`** (match `STACK_VERSION`); strengthen `FORTIGATE_TOKEN`.
4. Delete legacy `auth/user_store.py` + `data/users.json`.
