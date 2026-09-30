"""Add per-user dashboard widget layout.

Revision ID: 20260930_0009
Revises: 20260926_0008
Create Date: 2026-09-30

Clients can choose which service cards appear on their home page and in
what order. The layout is stored as a JSON list of widget keys. NULL means
the client has never customised the page, so existing users keep seeing
every card exactly as before.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260930_0009"
down_revision = "20260926_0008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("dashboard_layout", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("dashboard_layout")
