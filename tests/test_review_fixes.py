"""Regression tests for the security/bug-review patches."""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from api.app import app, _is_safe_next  # noqa: E402
from models import db, User, Service, Subscription  # noqa: E402
from security import hash_password  # noqa: E402
from secret_utils import is_placeholder_secret  # noqa: E402
from validation.common import host_address  # noqa: E402
from validation.errors import ValidationError  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    app.config["SQLALCHEMY_DATABASE_URI"]  # engine already bound to in-memory/ env URL
    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add(User(username="alice", password_hash=hash_password("correct-horse-battery"), salt="", role="client"))
        db.session.add(User(username="boss", password_hash=hash_password("correct-horse-battery"), salt="", role="admin"))
        db.session.commit()
    yield app.test_client()
    with app.app_context():
        db.session.remove()


def _csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


@pytest.mark.parametrize("target", ["/\\evil.example", "//evil.example", "https://evil.example", "/ok\r\nSet-Cookie: x=1", "evil", ""])
def test_unsafe_next_targets_rejected(target):
    assert not _is_safe_next(target)


@pytest.mark.parametrize("target", ["/client/", "/client/policies?device_id=1"])
def test_safe_next_targets_allowed(target):
    assert _is_safe_next(target)


def test_login_does_not_follow_backslash_next(client):
    token = _csrf(client)
    r = client.post(
        "/login?next=/%5Cevil.example",
        data={"username": "alice", "password": "correct-horse-battery", "csrf_token": token},
    )
    assert r.status_code == 302
    assert "evil" not in r.headers["Location"]


def test_csrf_failure_returns_400_not_500(client):
    r = client.post("/login", data={"username": "alice", "password": "x"})
    assert r.status_code == 400
    assert "X-Request-ID" in r.headers


def test_request_id_header_is_sanitised(client):
    r = client.get("/livez", headers={"X-Request-ID": "bad id with spaces\"<script>"})
    assert re.fullmatch(r"[0-9a-f-]{36}", r.headers["X-Request-ID"])


def test_expired_subscription_denies_access(client):
    from client.access import has_active_service_subscription

    with app.app_context():
        svc = Service(name="PE", service_type="policy_evaluation")
        db.session.add(svc)
        db.session.flush()
        user = User.query.filter_by(username="alice").one()
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        db.session.add(Subscription(user_id=user.id, service_id=svc.id, is_active=True,
                                    start_date=past - timedelta(days=30), end_date=past))
        db.session.commit()
        assert has_active_service_subscription(user.id, "policy_evaluation") is False

        sub = Subscription.query.one()
        sub.end_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
        db.session.commit()
        assert has_active_service_subscription(user.id, "policy_evaluation") is True


def test_placeholder_secrets_detected():
    assert is_placeholder_secret("change-me-please")
    assert is_placeholder_secret("development-only-secret")
    assert not is_placeholder_secret("p9fQ2sV7xLk0aZ3mWnB8rT5yHd1uJc4E")


@pytest.mark.parametrize("value", ["192.0.2.10", "fw.example.com:8443", "https://fw.example.com"])
def test_host_address_accepts_host_forms(value):
    assert host_address(value) == value


@pytest.mark.parametrize("value", [
    "http://169.254.169.254/latest/meta-data", "fw/../x", "user:pw@fw.example",
    "fw.example:99999", "10.0.0.1?x=1", "ftp://fw", "-bad.example",
])
def test_host_address_rejects_urls_and_junk(value):
    with pytest.raises(ValidationError):
        host_address(value)


def test_last_admin_cannot_be_deleted_or_demoted(client):
    token = _csrf(client)
    client.post("/login", data={"username": "boss", "password": "correct-horse-battery", "csrf_token": token})
    with app.app_context():
        boss_id = User.query.filter_by(username="boss").one().id
    token = _csrf(client, "/admin/users")  # any page that renders a csrf token
    r = client.post(f"/admin/users/{boss_id}/edit",
                    data={"username": "boss", "role": "client", "csrf_token": token})
    assert b"last administrator" in r.data
    with app.app_context():
        assert User.query.filter_by(username="boss").one().role == "admin"
