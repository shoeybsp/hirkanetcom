"""Adopt the existing Hirkanet schema under Alembic management.

Revision ID: 20260731_0001
Revises: None
Create Date: 2026-07-31

The migration checks for existing tables so an installation created by the
legacy db.create_all() startup path can be adopted without destructive table
recreation. It creates only tables and indexes that are missing.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260731_0001"
down_revision = None
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    tables = _tables()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("salt", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
    if "ix_users_username" not in _indexes("users"):
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    tables = _tables()
    if "services" not in tables:
        op.create_table(
            "services",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("service_type", sa.String(length=100), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    tables = _tables()
    if "blog_categories" not in tables:
        op.create_table(
            "blog_categories",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=140), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
            sa.UniqueConstraint("slug"),
        )
    if "ix_blog_categories_slug" not in _indexes("blog_categories"):
        op.create_index("ix_blog_categories_slug", "blog_categories", ["slug"], unique=True)

    tables = _tables()
    if "subscriptions" not in tables:
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    tables = _tables()
    if "blog_posts" not in tables:
        op.create_table(
            "blog_posts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("slug", sa.String(length=220), nullable=False),
            sa.Column("excerpt", sa.String(length=400), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("cover_image", sa.String(length=300), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=True),
            sa.Column("author_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["category_id"], ["blog_categories.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
    if "ix_blog_posts_slug" not in _indexes("blog_posts"):
        op.create_index("ix_blog_posts_slug", "blog_posts", ["slug"], unique=True)


def downgrade():
    # Destructive by design. Back up production data before downgrading.
    op.drop_index("ix_blog_posts_slug", table_name="blog_posts")
    op.drop_table("blog_posts")
    op.drop_table("subscriptions")
    op.drop_index("ix_blog_categories_slug", table_name="blog_categories")
    op.drop_table("blog_categories")
    op.drop_table("services")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
