"""Tests for api_v2's API-key authentication flow.

Isolated from the existing Flask test suite: uses its own temporary
SQLite database, provisioned with the real Alembic migrations (not
api_v2.models.Base.metadata.create_all(), so the schema under test is
identical to what production actually runs), and seeded via Flask's own
models.py ORM - the same tables api_v2 then reads through its separate,
plain-SQLAlchemy models. This is deliberately an integration test proving
the two ORMs interoperate on one schema, not a unit test with mocks.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def api_v2_test_env(tmp_path_factory):
    """Provision a fresh, migrated SQLite database and point every
    process/import at it before api_v2 (and its module-level engine) is
    ever imported."""
    db_path = tmp_path_factory.mktemp("api_v2_db") / "test.db"
    database_url = f"sqlite:///{db_path}"

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["APP_ENV"] = "development"
    env["SECRET_KEY"] = "testkey"
    env["DEVICE_CREDENTIAL_KEY"] = "testcredkey"
    env.pop("POSTGRES_HOST", None)

    subprocess.run(
        [sys.executable, "-m", "flask", "--app", "api.app", "db", "upgrade"],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )

    os.environ["DATABASE_URL"] = database_url
    os.environ["APP_ENV"] = "development"
    os.environ["SECRET_KEY"] = "testkey"
    os.environ["DEVICE_CREDENTIAL_KEY"] = "testcredkey"
    os.environ.pop("POSTGRES_HOST", None)

    yield database_url

    os.environ.pop("DATABASE_URL", None)


@pytest.fixture(scope="module")
def seeded_data(api_v2_test_env):
    """Seed a user, a device, an assignment, and two API keys (one active,
    one revoked) using Flask's own ORM - the same rows api_v2 will later
    read through its separate plain-SQLAlchemy models."""
    from api.app import app
    from models import db, User, Device, DeviceAssignment, ApiKey
    from security import hash_password
    from api_keys import generate_api_key, hash_api_key

    with app.app_context():
        user = User(username="apiuser", password_hash=hash_password("apiuser-password-123"), salt="", role="client")
        db.session.add(user)
        db.session.commit()

        device = Device(name="API Test Device", device_type="fortigate", data_dir="data/devices/apitest", is_active=True)
        db.session.add(device)
        db.session.commit()

        db.session.add(DeviceAssignment(user_id=user.id, device_id=device.id, is_active=True))

        active_raw = generate_api_key()
        db.session.add(ApiKey(user_id=user.id, key_hash=hash_api_key(active_raw), label="active"))

        revoked_raw = generate_api_key()
        from datetime import datetime, timezone
        db.session.add(ApiKey(user_id=user.id, key_hash=hash_api_key(revoked_raw), label="revoked", revoked_at=datetime.now(timezone.utc)))

        db.session.commit()

        return {
            "user_id": user.id,
            "username": user.username,
            "device_id": device.id,
            "active_key": active_raw,
            "revoked_key": revoked_raw,
        }


@pytest.fixture(scope="module")
def client(seeded_data):
    import importlib

    import api_v2.db as api_v2_db
    importlib.reload(api_v2_db)
    import api_v2.auth as api_v2_auth
    importlib.reload(api_v2_auth)
    import api_v2.main as api_v2_main
    importlib.reload(api_v2_main)

    from fastapi.testclient import TestClient

    return TestClient(api_v2_main.app)


def test_livez(client):
    resp = client.get("/livez")
    assert resp.status_code == 200


def test_readyz(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200


def test_missing_key_is_401(client):
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_wrong_key_is_401(client):
    resp = client.get("/whoami", headers={"X-API-Key": "hnk_totally_wrong_key"})
    assert resp.status_code == 401


def test_valid_key_resolves_correct_user(client, seeded_data):
    resp = client.get("/whoami", headers={"X-API-Key": seeded_data["active_key"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == seeded_data["user_id"]
    assert body["username"] == seeded_data["username"]


def test_revoked_key_is_401(client, seeded_data):
    resp = client.get("/whoami", headers={"X-API-Key": seeded_data["revoked_key"]})
    assert resp.status_code == 401


def test_valid_key_updates_last_used_at(client, seeded_data):
    from api.app import app
    from models import ApiKey
    import hashlib
    import time

    key_hash = hashlib.sha256(seeded_data["active_key"].encode("utf-8")).hexdigest()

    with app.app_context():
        before = ApiKey.query.filter_by(key_hash=key_hash).first().last_used_at

    time.sleep(0.01)  # ensure a strictly later timestamp even at low clock resolution
    client.get("/whoami", headers={"X-API-Key": seeded_data["active_key"]})

    with app.app_context():
        after = ApiKey.query.filter_by(key_hash=key_hash).first().last_used_at
        assert after is not None
        if before is not None:
            assert after > before


def test_has_device_access_matches_assignment(seeded_data):
    from api_v2.db import SessionLocal
    from api_v2.access import has_device_access

    session = SessionLocal()
    try:
        assert has_device_access(session, seeded_data["user_id"], seeded_data["device_id"]) is True
        assert has_device_access(session, seeded_data["user_id"], 999999) is False
    finally:
        session.close()
