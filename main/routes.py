from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, abort, request
from flask_login import current_user

from models import BlogCategory, BlogPost

main_bp = Blueprint("main", __name__)

POSTS_PER_PAGE = 9


@main_bp.context_processor
def inject_globals():
    return {"current_year": datetime.now(timezone.utc).year}


def _role_redirect():
    """Send an already-authenticated visitor straight to their dashboard."""
    if current_user.role == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("client.dashboard"))


@main_bp.route("/")
def home():
    if current_user.is_authenticated:
        return _role_redirect()

    latest_posts = (
        BlogPost.query.filter_by(status="published")
        .order_by(BlogPost.published_at.desc())
        .limit(3)
        .all()
    )
    return render_template("main/home.html", latest_posts=latest_posts)


@main_bp.route("/blog")
def blog_list():
    category_slug = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int) or 1
    page = max(page, 1)

    query = BlogPost.query.filter_by(status="published")

    active_category = None
    if category_slug:
        active_category = BlogCategory.query.filter_by(slug=category_slug).first()
        if active_category is None:
            abort(404)
        query = query.filter(BlogPost.category_id == active_category.id)

    query = query.order_by(BlogPost.published_at.desc())

    total = query.count()
    total_pages = max(1, (total + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)
    page = min(page, total_pages)

    posts = query.offset((page - 1) * POSTS_PER_PAGE).limit(POSTS_PER_PAGE).all()
    categories = BlogCategory.query.order_by(BlogCategory.name).all()

    return render_template(
        "main/blog_list.html",
        posts=posts,
        categories=categories,
        active_category=active_category,
        page=page,
        total_pages=total_pages,
    )


@main_bp.route("/blog/<slug>")
def blog_detail(slug):
    post = BlogPost.query.filter_by(slug=slug).first()
    if post is None or post.status != "published":
        abort(404)

    related_posts = []
    if post.category_id:
        related_posts = (
            BlogPost.query.filter(
                BlogPost.category_id == post.category_id,
                BlogPost.id != post.id,
                BlogPost.status == "published",
            )
            .order_by(BlogPost.published_at.desc())
            .limit(3)
            .all()
        )

    return render_template("main/blog_detail.html", post=post, related_posts=related_posts)
