"""Add database-backed login rate limiting.

Revision ID: 20260801_0004
Revises: 20260731_0003
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260801_0004"
down_revision = "20260731_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "login_rate_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_epoch", sa.BigInteger(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until_epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at_epoch", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("scope IN ('username', 'ip')", name="ck_login_rate_limits_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "identifier_hash",
            name="uq_login_rate_limits_scope_identifier",
        ),
    )
    op.create_index(
        "ix_login_rate_limits_blocked_until",
        "login_rate_limits",
        ["blocked_until_epoch"],
        unique=False,
    )
    op.create_index(
        "ix_login_rate_limits_updated_at",
        "login_rate_limits",
        ["updated_at_epoch"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_login_rate_limits_updated_at", table_name="login_rate_limits")
    op.drop_index("ix_login_rate_limits_blocked_until", table_name="login_rate_limits")
    op.drop_table("login_rate_limits")
