"""Regression tests for database-backed login rate limiting."""

from flask import Flask

from auth.rate_limit import (
    check_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from models import LoginRateLimit, db


def _app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-rate-limit-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS=2,
        LOGIN_RATE_LIMIT_IP_ATTEMPTS=3,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=60,
        LOGIN_RATE_LIMIT_BLOCK_SECONDS=120,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app


def test_username_limit_blocks_and_returns_retry_after():
    app = _app()
    with app.app_context():
        assert check_login_allowed("alice", "192.0.2.10", now=1000).allowed
        assert record_login_failure("alice", "192.0.2.10", now=1000).allowed

        decision = record_login_failure("alice", "192.0.2.10", now=1001)
        assert not decision.allowed
        assert decision.scope == "username"
        assert decision.retry_after == 120

        blocked = check_login_allowed("alice", "192.0.2.10", now=1010)
        assert not blocked.allowed
        assert blocked.retry_after == 111


def test_source_ip_limit_spans_different_usernames():
    app = _app()
    with app.app_context():
        assert record_login_failure("alice", "192.0.2.20", now=2000).allowed
        assert record_login_failure("bob", "192.0.2.20", now=2001).allowed
        decision = record_login_failure("carol", "192.0.2.20", now=2002)
        assert not decision.allowed
        assert decision.scope == "ip"


def test_success_clears_only_username_counter():
    app = _app()
    with app.app_context():
        record_login_failure("alice", "192.0.2.30", now=3000)
        clear_login_failures("alice")

        rows = LoginRateLimit.query.all()
        assert len(rows) == 1
        assert rows[0].scope == "ip"
        assert check_login_allowed("alice", "192.0.2.31", now=3001).allowed


def test_identifiers_are_not_stored_in_plaintext():
    app = _app()
    with app.app_context():
        record_login_failure("alice@example.com", "192.0.2.40", now=4000)
        rows = LoginRateLimit.query.all()
        assert len(rows) == 2
        assert all(len(row.identifier_hash) == 64 for row in rows)
        assert all("alice" not in row.identifier_hash for row in rows)
        assert all("192.0.2.40" not in row.identifier_hash for row in rows)
