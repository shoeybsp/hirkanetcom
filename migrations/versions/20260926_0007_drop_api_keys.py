"""Drop api_keys table — FastAPI pilot removed.

Revision ID: 20260926_0007
Revises: 20260802_0005
Create Date: 2026-09-26

Replaces the deleted 20260803_0006 (api_keys) migration. Drops the
api_keys table that was created for the FastAPI pilot service, which
has been fully rolled out of the project.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0007"
down_revision = "20260803_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")


def downgrade():
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
