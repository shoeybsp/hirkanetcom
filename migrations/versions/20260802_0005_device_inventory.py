"""Add device inventory and client-device assignment tables.

Revision ID: 20260802_0005
Revises: 20260801_0004
Create Date: 2026-08-02

Introduces multi-device support: the "devices" table replaces the single
implicit FortiGate configuration with an admin-managed inventory, and
"device_assignments" grants individual client users access to evaluate
policies against a specific device. Existing single-device installs are
migrated forward by models.seed_defaults(), which registers the existing
top-level "data" directory as a Device row the first time this runs -
no snapshot files are moved by this migration.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260802_0005"
down_revision = "20260801_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False, server_default="fortigate"),
        sa.Column("api_host", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("api_scheme", sa.String(length=10), nullable=False, server_default="https"),
        sa.Column("vdom", sa.String(length=100), nullable=False, server_default="root"),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("skip_monitor_routes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("keep_snapshots", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("auth_username_encrypted", sa.Text(), nullable=True),
        sa.Column("auth_password_encrypted", sa.Text(), nullable=True),
        sa.Column("data_dir", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("last_sync_message", sa.Text(), nullable=True),
        sa.Column("last_snapshot_id", sa.String(length=150), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("data_dir"),
        sa.CheckConstraint("device_type IN ('fortigate')", name="ck_devices_device_type"),
        sa.CheckConstraint(
            "last_sync_status IS NULL OR last_sync_status IN ('success', 'failure')",
            name="ck_devices_last_sync_status",
        ),
    )
    op.create_index("ix_devices_type_active", "devices", ["device_type", "is_active"], unique=False)

    op.create_table(
        "device_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "device_id", name="uq_device_assignments_user_device"),
    )
    op.create_index(
        "ix_device_assignments_user_active",
        "device_assignments",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_device_assignments_device_active",
        "device_assignments",
        ["device_id", "is_active"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_device_assignments_device_active", table_name="device_assignments")
    op.drop_index("ix_device_assignments_user_active", table_name="device_assignments")
    op.drop_table("device_assignments")

    op.drop_index("ix_devices_type_active", table_name="devices")
    op.drop_table("devices")
