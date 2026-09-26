"""Drop blog_posts and blog_categories tables.

Revision ID: 20260926_0008
Revises: 20260926_0007
Create Date: 2026-09-26

Removes the blog CMS subsystem. blog_posts has a foreign key to
blog_categories, so it must be dropped first.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0008"
down_revision = "20260926_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_blog_posts_slug", table_name="blog_posts")
    op.drop_index("ix_blog_posts_category_status", table_name="blog_posts")
    op.drop_index("ix_blog_posts_status_published_at", table_name="blog_posts")
    op.drop_table("blog_posts")
    op.drop_index("ix_blog_categories_slug", table_name="blog_categories")
    op.drop_table("blog_categories")


def downgrade():
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
    op.create_index("ix_blog_categories_slug", "blog_categories", ["slug"], unique=True)

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
        sa.ForeignKeyConstraint(
            ["category_id"], ["blog_categories.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_blog_posts_slug", "blog_posts", ["slug"], unique=True
    )
    op.create_index(
        "ix_blog_posts_status_published_at",
        "blog_posts",
        ["status", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_blog_posts_category_status",
        "blog_posts",
        ["category_id", "status"],
        unique=False,
    )
