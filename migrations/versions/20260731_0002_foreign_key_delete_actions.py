"""Enforce database-level foreign-key deletion behavior.

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31

Subscriptions are owned by users and services, so those references cascade.
Blog posts are retained when an author or category is deleted, so those
references are set to NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260731_0002"
down_revision = "20260731_0001"
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _replace_foreign_key(table_name, local_column, referred_table, referred_column, ondelete):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys(table_name)
    matching = [
        fk for fk in foreign_keys
        if fk.get("constrained_columns") == [local_column]
        and fk.get("referred_table") == referred_table
    ]

    if bind.dialect.name == "sqlite":
        # Batch mode recreates the table because SQLite cannot alter FKs in place.
        with op.batch_alter_table(
            table_name,
            recreate="always",
            naming_convention=_NAMING_CONVENTION,
        ) as batch_op:
            for fk in matching:
                name = fk.get("name") or f"fk_{table_name}_{local_column}_{referred_table}"
                batch_op.drop_constraint(name, type_="foreignkey")
            batch_op.create_foreign_key(
                f"fk_{table_name}_{local_column}_{referred_table}",
                referred_table,
                [local_column],
                [referred_column],
                ondelete=ondelete,
            )
        return

    for fk in matching:
        if fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")

    op.create_foreign_key(
        f"fk_{table_name}_{local_column}_{referred_table}",
        table_name,
        referred_table,
        [local_column],
        [referred_column],
        ondelete=ondelete,
    )


def upgrade():
    _replace_foreign_key("subscriptions", "user_id", "users", "id", "CASCADE")
    _replace_foreign_key("subscriptions", "service_id", "services", "id", "CASCADE")
    _replace_foreign_key("blog_posts", "author_id", "users", "id", "SET NULL")
    _replace_foreign_key("blog_posts", "category_id", "blog_categories", "id", "SET NULL")


def downgrade():
    _replace_foreign_key("subscriptions", "user_id", "users", "id", None)
    _replace_foreign_key("subscriptions", "service_id", "services", "id", None)
    _replace_foreign_key("blog_posts", "author_id", "users", "id", None)
    _replace_foreign_key("blog_posts", "category_id", "blog_categories", "id", None)
