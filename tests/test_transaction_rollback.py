from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from database_transactions import (
    DatabaseConflictError,
    DatabaseTransactionError,
    commit_transaction,
    transaction,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeSession:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1


def test_integrity_failure_rolls_back_and_raises_conflict():
    error = IntegrityError("insert", {}, Exception("duplicate"))
    session = FakeSession(error)

    with pytest.raises(DatabaseConflictError):
        commit_transaction("create user", session=session)

    assert session.commits == 1
    assert session.rollbacks == 1


def test_database_failure_rolls_back_and_raises_safe_error():
    error = OperationalError("update", {}, Exception("connection lost"))
    session = FakeSession(error)

    with pytest.raises(DatabaseTransactionError):
        commit_transaction("update service", session=session)

    assert session.commits == 1
    assert session.rollbacks == 1


def test_context_rolls_back_when_flush_or_application_work_fails():
    session = FakeSession()

    with pytest.raises(RuntimeError):
        with transaction("seed defaults", session=session):
            raise RuntimeError("seed failed")

    assert session.commits == 0
    assert session.rollbacks == 1


def test_context_commits_once_on_success():
    session = FakeSession()

    with transaction("successful operation", session=session):
        pass

    assert session.commits == 1
    assert session.rollbacks == 0


def test_application_writes_do_not_call_commit_directly():
    allowed = {ROOT / "database_transactions.py"}
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path in allowed or "migrations" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "db.session.commit(" in text or ".session.commit(" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_database_error_template_and_handler_exist():
    app_source = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
    template = ROOT / "templates" / "main" / "database_error.html"
    assert "@app.errorhandler(DatabaseTransactionError)" in app_source
    assert template.exists()
