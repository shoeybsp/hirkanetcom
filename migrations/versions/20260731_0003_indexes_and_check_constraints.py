"""Add data-integrity constraints and query indexes.

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31

The migration fails before changing the schema when existing rows violate the
new invariants. Administrators must correct those rows deliberately rather than
having a migration silently rewrite production data.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260731_0003"
down_revision = "20260731_0002"
branch_labels = None
depends_on = None


def _scalar_count(sql):
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _validate_existing_data():
    violations = []

    if _scalar_count("SELECT COUNT(*) FROM users WHERE role NOT IN ('admin', 'client')"):
        violations.append("users.role contains values outside admin/client")

    if _scalar_count("SELECT COUNT(*) FROM services WHERE service_type IS NULL OR length(trim(service_type)) = 0"):
        violations.append("services.service_type contains blank values")

    if _scalar_count("SELECT COUNT(*) FROM blog_posts WHERE status NOT IN ('draft', 'published')"):
        violations.append("blog_posts.status contains values outside draft/published")

    if _scalar_count(
        "SELECT COUNT(*) FROM subscriptions "
        "WHERE end_date IS NOT NULL AND (start_date IS NULL OR end_date <= start_date)"
    ):
        violations.append("subscriptions contains invalid start/end date ranges")

    duplicate_groups = _scalar_count(
        "SELECT COUNT(*) FROM ("
        "SELECT user_id, service_id FROM subscriptions "
        "GROUP BY user_id, service_id HAVING COUNT(*) > 1"
        ") AS duplicate_subscriptions"
    )
    if duplicate_groups:
        violations.append("subscriptions contains duplicate user/service pairs")

    if violations:
        details = "; ".join(violations)
        raise RuntimeError(
            "Cannot apply revision 20260731_0003 because existing data violates "
            f"the new constraints: {details}. Correct the data and rerun flask db upgrade."
        )


def _constraint_names(table_name, kind):
    inspector = sa.inspect(op.get_bind())
    if kind == "check":
        return {item.get("name") for item in inspector.get_check_constraints(table_name)}
    if kind == "unique":
        return {item.get("name") for item in inspector.get_unique_constraints(table_name)}
    raise ValueError(kind)


def _index_names(table_name):
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_check(table_name, name, condition):
    if name in _constraint_names(table_name, "check"):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            batch_op.create_check_constraint(name, condition)
    else:
        op.create_check_constraint(name, table_name, condition)


def _create_unique(table_name, name, columns):
    if name in _constraint_names(table_name, "unique"):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            batch_op.create_unique_constraint(name, columns)
    else:
        op.create_unique_constraint(name, table_name, columns)


def _create_index(table_name, name, columns):
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, unique=False)


def upgrade():
    _validate_existing_data()

    _create_check("users", "ck_users_role", "role IN ('admin', 'client')")
    _create_check(
        "services",
        "ck_services_service_type_not_blank",
        "length(trim(service_type)) > 0",
    )
    _create_check(
        "subscriptions",
        "ck_subscriptions_valid_date_range",
        "end_date IS NULL OR end_date > start_date",
    )
    _create_check(
        "blog_posts",
        "ck_blog_posts_status",
        "status IN ('draft', 'published')",
    )
    _create_unique(
        "subscriptions",
        "uq_subscriptions_user_service",
        ["user_id", "service_id"],
    )

    _create_index("services", "ix_services_type_active", ["service_type", "is_active"])
    _create_index("subscriptions", "ix_subscriptions_user_active", ["user_id", "is_active"])
    _create_index("subscriptions", "ix_subscriptions_service_active", ["service_id", "is_active"])
    _create_index("blog_posts", "ix_blog_posts_status_published_at", ["status", "published_at"])
    _create_index("blog_posts", "ix_blog_posts_category_status", ["category_id", "status"])


def _drop_constraint(table_name, name, type_):
    names = _constraint_names(table_name, "check" if type_ == "check" else "unique")
    if name not in names:
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            batch_op.drop_constraint(name, type_=type_)
    else:
        op.drop_constraint(name, table_name, type_=type_)


def downgrade():
    for table_name, index_name in [
        ("blog_posts", "ix_blog_posts_category_status"),
        ("blog_posts", "ix_blog_posts_status_published_at"),
        ("subscriptions", "ix_subscriptions_service_active"),
        ("subscriptions", "ix_subscriptions_user_active"),
        ("services", "ix_services_type_active"),
    ]:
        if index_name in _index_names(table_name):
            op.drop_index(index_name, table_name=table_name)

    _drop_constraint("subscriptions", "uq_subscriptions_user_service", "unique")
    _drop_constraint("blog_posts", "ck_blog_posts_status", "check")
    _drop_constraint("subscriptions", "ck_subscriptions_valid_date_range", "check")
    _drop_constraint("services", "ck_services_service_type_not_blank", "check")
    _drop_constraint("users", "ck_users_role", "check")
