"""Database engine/session setup for the FastAPI service.

Uses db_url.resolve_database_url() - the same resolution logic the Flask
app uses via models.py::init_db - so both services always connect to
identically the same database, with no separate configuration to drift.

This is plain SQLAlchemy (Session, not Flask-SQLAlchemy's query API),
since this service has no Flask application context to hang a
Flask-SQLAlchemy extension off of.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db_url import resolve_database_url

engine = create_engine(resolve_database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped Session, closed after use."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
