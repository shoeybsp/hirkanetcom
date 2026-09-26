"""Framework-agnostic database URL resolution.

Extracted from models.py so that any service sharing this database
resolves the connection the exact same way. models.py::init_db calls
resolve_database_url() too; this module has no Flask dependency.

Resolution order: DATABASE_URL > POSTGRES_HOST > local SQLite fallback.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import URL

from secret_utils import read_secret

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def default_database_url() -> str:
    """Return a local SQLite database path when no database URL is configured."""
    return f"sqlite:///{os.path.join(REPO_DIR, 'fortigate_policy.db')}"


def normalize_database_url(database_url: str) -> str:
    """Normalize SQLite URLs to a form accepted by SQLAlchemy."""
    if not database_url.startswith("sqlite"):
        return database_url

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return database_url

    if not parsed.path or parsed.path in (":memory:", "/:memory:"):
        return "sqlite:///:memory:"

    if os.path.isabs(parsed.path):
        return f"sqlite:////{parsed.path.lstrip('/')}"

    return f"sqlite:///{parsed.path}"


def ensure_database_path(database_url: str) -> None:
    """Create parent directories for SQLite database files before connecting."""
    if not database_url.startswith("sqlite"):
        return

    parsed = urlparse(database_url)
    database_path = parsed.path
    if not database_path or database_path in (":memory:", "/:memory:"):
        return

    parent_dir = os.path.dirname(database_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def resolve_database_url():
    """Resolve the database URL the same way for every service that needs one.

    Returns either a plain string (SQLite) or a `sqlalchemy.URL` object
    (Postgres - kept as a URL object rather than a string so the password
    is never masked by an accidental str() call). As a side effect,
    ensures the SQLite parent directory exists when that branch is taken.
    """
    configured_url = os.environ.get("DATABASE_URL")

    if configured_url:
        database_url = normalize_database_url(configured_url)
        ensure_database_path(database_url)
        return database_url

    if os.getenv("POSTGRES_HOST"):
        return URL.create(
            "postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"),
            password=read_secret("POSTGRES_PASSWORD", required=True),
            host=os.getenv("POSTGRES_HOST", "db"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB"),
        )

    database_url = normalize_database_url(default_database_url())
    ensure_database_path(database_url)
    return database_url
