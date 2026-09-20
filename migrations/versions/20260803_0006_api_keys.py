"""Add api_keys table for the FastAPI pilot service.

Revision ID: 20260803_0006
Revises: 20260802_0005
Create Date: 2026-08-03

API keys authenticate the new FastAPI service (api_v2/) against existing
User rows - not a separate identity concept - so authorization logic like
has_device_access has exactly one source of truth regardless of whether
the caller is the session-based web UI or a programmatic API key. Only a
SHA-256 hash of each key is ever stored; the raw key is shown once at
issuance time.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260803_0006"
down_revision = "20260802_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
