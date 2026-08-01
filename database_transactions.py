"""Centralized SQLAlchemy transaction handling.

All application writes must pass through this module so a failed flush or
commit always rolls the scoped session back before it can be reused.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _default_session():
    # Imported lazily to keep this helper independently testable and avoid
    # circular imports while models are being initialized.
    from models import db

    return db.session


class DatabaseTransactionError(RuntimeError):
    """Base error for a database transaction that was rolled back."""

    status_code = 500
    public_message = "The database operation failed. No changes were saved."

    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(f"Database transaction failed during: {operation}")


class DatabaseConflictError(DatabaseTransactionError):
    """A transaction violated a uniqueness or integrity constraint."""

    status_code = 409
    public_message = (
        "The requested change conflicts with existing or related data. "
        "No changes were saved."
    )


def _rollback(session: Session, operation: str, exc: BaseException) -> None:
    """Rollback defensively and log the original transaction failure."""
    try:
        session.rollback()
    except SQLAlchemyError:
        logger.exception(
            "Database rollback also failed",
            extra={"event_type": "database_rollback_failure", "operation": operation},
        )

    logger.exception(
        "Database transaction rolled back",
        exc_info=exc,
        extra={"event_type": "database_transaction_rollback", "operation": operation},
    )


def commit_transaction(operation: str, *, session: Session | None = None) -> None:
    """Commit the current unit of work or rollback and raise a safe error."""
    active_session = session if session is not None else _default_session()
    try:
        active_session.commit()
    except IntegrityError as exc:
        _rollback(active_session, operation, exc)
        raise DatabaseConflictError(operation) from exc
    except SQLAlchemyError as exc:
        _rollback(active_session, operation, exc)
        raise DatabaseTransactionError(operation) from exc


@contextmanager
def transaction(operation: str, *, session: Session | None = None) -> Iterator[Session]:
    """Wrap a complete unit of work, including explicit flush operations."""
    active_session = session if session is not None else _default_session()
    try:
        yield active_session
        active_session.commit()
    except IntegrityError as exc:
        _rollback(active_session, operation, exc)
        raise DatabaseConflictError(operation) from exc
    except SQLAlchemyError as exc:
        _rollback(active_session, operation, exc)
        raise DatabaseTransactionError(operation) from exc
    except Exception:
        # Non-SQLAlchemy failures can still happen after the session has staged
        # changes. Roll them back before propagating the original exception.
        try:
            active_session.rollback()
        except SQLAlchemyError:
            logger.exception(
                "Database rollback failed after application error",
                extra={"event_type": "database_rollback_failure", "operation": operation},
            )
        raise
