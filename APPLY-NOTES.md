# FastAPI migration - Phase 1, verified against your actual uploaded codebase

Unlike earlier phases, this was NOT built against a hand-reconstruction -
your hirkanetcom.zip was unzipped, these exact changes applied on top of
it, and both the test suite and a live server were run directly against
your real files. docker-compose.yml here is your real file with the
api_v2 block added, not a transcription.

## One pre-existing bug found and fixed, unrelated to this phase

tests/test_app_container_hardening.py::test_only_declared_runtime_paths_are_writable
was already failing in your repo before I touched anything - it still
asserted the old bind-mount form (./data:/app/data), never updated after
your own "change bind docker volume to named volume" commit. Confirmed via
a from-scratch pytest run before any Phase 1 changes: 22 failures, not the
usual 21. Fixed to check for hirkanet_data:/app/data instead; confirmed
this is the only test with that stale assumption.

## New files (11)

    db_url.py
    api_keys.py
    api_v2/__init__.py
    api_v2/db.py
    api_v2/models.py
    api_v2/access.py
    api_v2/auth.py
    api_v2/main.py
    Dockerfile.api_v2
    requirements-api_v2.txt
    migrations/versions/20260803_0006_api_keys.py
    tests/test_api_v2_auth.py

## Modified files (6)

    models.py                             + ApiKey model; init_db now calls
                                            db_url.resolve_database_url()
    api/app.py                            + click import; + issue-api-key
                                            CLI command
    docker-compose.yml                    + api_v2 service (your db/migrate/
                                            app services and volumes/networks
                                            blocks are untouched)
    tests/test_secret_configuration.py    updated for db_url.py relocation
    tests/test_compose_split.py           updated for the new api_v2 service
    tests/test_app_container_hardening.py the pre-existing fix described above

## Deliberately NOT included

    .env and secrets/*         contain your live secret values; already
                                correct on your end, no reason to route
                                them through this delivery
    .git, __pycache__, etc.    not touched, no reason to re-deliver

## Apply

    cp db_url.py api_keys.py models.py Dockerfile.api_v2 \
       requirements-api_v2.txt docker-compose.yml /path/to/hirkanetcom/
    cp api/app.py /path/to/hirkanetcom/api/
    cp -r api_v2 /path/to/hirkanetcom/
    cp migrations/versions/20260803_0006_api_keys.py \
       /path/to/hirkanetcom/migrations/versions/
    cp tests/test_api_v2_auth.py tests/test_secret_configuration.py \
       tests/test_compose_split.py tests/test_app_container_hardening.py \
       /path/to/hirkanetcom/tests/

Since docker-compose.yml here IS your real file plus the api_v2 block
(not a reconstruction this time), it's safe to overwrite directly -
though diffing first is never a bad habit.

## What was verified, against these exact files, not a copy

- Established true baseline first: fresh pytest run on your untouched
  upload showed 22 failures (the extra one being the pre-existing bug
  above) - confirmed BEFORE making any changes, so credit/blame is
  correctly attributed.
- After applying: 145 passed, 21 failed (back to the known baseline, the
  8 new api_v2 tests now passing).
- Ran the full Alembic chain from scratch through 20260803_0006 with no
  errors, using your actual migrations/ directory.
- Started a real uvicorn process against your actual models.py/api_v2
  code and a freshly migrated database. Verified live: missing key -> 401,
  wrong key -> 401, valid key -> 200 with correct user (admin, id=1),
  last_used_at written and confirmed via Flask's ORM, and - critically -
  revoked the key through Flask's ORM while the FastAPI process was still
  running, and confirmed it was rejected on the very next request with no
  restart.
- docker-compose.yml YAML-validated and confirmed to declare exactly
  {app, db, migrate, api_v2}.

## What's still NOT verified (same caveat as before)

No Docker daemon available in this environment, so `docker compose up
--build` itself - both images actually building, healthchecks passing
inside real containers - has not been run. Everything above was verified
via a bare venv + uvicorn process + SQLite, which exercises the same code
paths but not the container layer itself. Worth watching
`docker compose logs migrate` and `docker compose logs api_v2` on your
first real `--build` the way the pre-flight checklist described.

## Next: Phase 2

The actual pilot endpoint - POST /api_v2/devices/{id}/sync - wired to
collectors/sync_service.py::run_device_sync. Not included here.
