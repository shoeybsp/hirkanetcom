"""Authentication forms and helpers backed exclusively by PostgreSQL models.

User identity, password hashes, and roles are stored in the SQLAlchemy ``User``
model. This package intentionally exposes no file-backed user store.
"""
