"""Plain SQLAlchemy models for the FastAPI service.

These map to the exact same tables models.py's Flask-SQLAlchemy classes
own - Alembic (driven from the Flask side) remains the single source of
schema truth; nothing here creates or alters tables. Only the columns this
service actually reads or writes are declared, deliberately kept narrower
than the full Flask-SQLAlchemy models to keep the drift surface small.

If a column used here is ever renamed or removed on the Flask side without
a matching update here, this service will fail loudly (AttributeError /
column-not-found) rather than silently - there is no runtime schema
validation tying the two together beyond that.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    key_hash: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    device_type: Mapped[str] = mapped_column(String(50))
    api_host: Mapped[str] = mapped_column(String(255))
    api_scheme: Mapped[str] = mapped_column(String(10))
    vdom: Mapped[str] = mapped_column(String(100))
    verify_ssl: Mapped[bool] = mapped_column(Boolean)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    skip_monitor_routes: Mapped[bool] = mapped_column(Boolean)
    keep_snapshots: Mapped[int] = mapped_column(Integer)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_username_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_dir: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_sync_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_snapshot_id: Mapped[str | None] = mapped_column(String(150), nullable=True)


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
