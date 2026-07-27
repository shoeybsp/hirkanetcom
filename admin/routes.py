import hashlib
import os
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from models import db, User, Service, Subscription, BlogCategory, BlogPost, slugify

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ALLOWED_COVER_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def admin_required(f):
    """Decorator to restrict access to admin users."""
    from functools import wraps

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("client.dashboard"))
        return f(*args, **kwargs)

    return decorated


# =============================================================================
# Admin Dashboard
# =============================================================================


@admin_bp.route("/")
@admin_required
def dashboard():
    """Admin dashboard overview."""
    user_count = User.query.count()
    service_count = Service.query.count()
    subscription_count = Subscription.query.count()
    blog_post_count = BlogPost.query.count()
    blog_category_count = BlogCategory.query.count()
    return render_template(
        "admin/dashboard.html",
        user_count=user_count,
        service_count=service_count,
        subscription_count=subscription_count,
        blog_post_count=blog_post_count,
        blog_category_count=blog_category_count,
    )


# =============================================================================
# User Management
# =============================================================================


@admin_bp.route("/users")
@admin_required
def user_list():
    """List all users."""
    users = User.query.order_by(User.username).all()
    return render_template("admin/user_list.html", users=users)


@admin_bp.route("/users/create", methods=["GET", "POST"])
@admin_required
def user_create():
    """Create a new user."""
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "client")

        if not username:
            flash("Username is required.", "error")
            return render_template("admin/user_form.html", user=None)

        if not password or len(password) < 4:
            flash("Password must be at least 4 characters.", "error")
            return render_template("admin/user_form.html", user=None)

        if role not in ("admin", "client"):
            flash("Invalid role.", "error")
            return render_template("admin/user_form.html", user=None)

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash(f"User '{username}' already exists.", "error")
            return render_template("admin/user_form.html", user=None)

        salt = os.urandom(32).hex()
        pw_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        user = User(username=username, password_hash=pw_hash, salt=salt, role=role)
        db.session.add(user)
        db.session.commit()

        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("admin.user_list"))

    return render_template("admin/user_form.html", user=None)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    """Edit a user."""
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "client")

        if not username:
            flash("Username is required.", "error")
            return render_template("admin/user_form.html", user=user)

        if role not in ("admin", "client"):
            flash("Invalid role.", "error")
            return render_template("admin/user_form.html", user=user)

        # Check if username is taken by another user
        existing = User.query.filter(User.username == username, User.id != user_id).first()
        if existing:
            flash(f"Username '{username}' is already taken.", "error")
            return render_template("admin/user_form.html", user=user)

        user.username = username
        user.role = role

        if password:
            if len(password) < 4:
                flash("Password must be at least 4 characters.", "error")
                return render_template("admin/user_form.html", user=user)
            salt = os.urandom(32).hex()
            pw_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            user.password_hash = pw_hash
            user.salt = salt

        db.session.commit()
        flash(f"User '{username}' updated successfully.", "success")
        return redirect(url_for("admin.user_list"))

    return render_template("admin/user_form.html", user=user)


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    """Delete a user."""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot delete yourself.", "error")
        return redirect(url_for("admin.user_list"))

    # Also remove their subscriptions
    Subscription.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    flash(f"User '{user.username}' deleted.", "success")
    return redirect(url_for("admin.user_list"))


# =============================================================================
# User Subscriptions (manage which services a user has access to)
# =============================================================================


@admin_bp.route("/users/<int:user_id>/subscriptions", methods=["GET", "POST"])
@admin_required
def user_subscriptions(user_id):
    """Manage which services a user is subscribed to."""
    user = User.query.get_or_404(user_id)
    services = Service.query.order_by(Service.name).all()

    if request.method == "POST":
        selected_service_ids = set(int(v) for v in request.form.getlist("services"))

        # Remove unselected subscriptions
        for sub in user.subscriptions:
            if sub.service_id not in selected_service_ids:
                db.session.delete(sub)

        # Add new subscriptions
        existing_ids = set(sub.service_id for sub in user.subscriptions)
        for svc_id in selected_service_ids:
            if svc_id not in existing_ids:
                sub = Subscription(user_id=user.id, service_id=svc_id, is_active=True)
                db.session.add(sub)

        db.session.commit()
        flash(f"Subscriptions for '{user.username}' updated.", "success")
        return redirect(url_for("admin.user_list"))

    return render_template(
        "admin/user_subscriptions.html",
        user=user,
        services=services,
    )


# =============================================================================
# Services Settings
# =============================================================================


@admin_bp.route("/services")
@admin_required
def service_list():
    """List all services."""
    services = Service.query.order_by(Service.name).all()
    return render_template("admin/service_list.html", services=services)


@admin_bp.route("/services/create", methods=["GET", "POST"])
@admin_required
def service_create():
    """Create a new service."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        service_type = request.form.get("service_type", "").strip()
        is_active = request.form.get("is_active") == "on"

        if not name or not service_type:
            flash("Name and Service Type are required.", "error")
            return render_template("admin/service_form.html", service=None)

        existing = Service.query.filter_by(name=name).first()
        if existing:
            flash(f"Service '{name}' already exists.", "error")
            return render_template("admin/service_form.html", service=None)

        svc = Service(
            name=name,
            description=description,
            service_type=service_type,
            is_active=is_active,
        )
        db.session.add(svc)
        db.session.commit()

        flash(f"Service '{name}' created.", "success")
        return redirect(url_for("admin.service_list"))

    return render_template("admin/service_form.html", service=None)


@admin_bp.route("/services/<int:service_id>/edit", methods=["GET", "POST"])
@admin_required
def service_edit(service_id):
    """Edit a service."""
    svc = Service.query.get_or_404(service_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        service_type = request.form.get("service_type", "").strip()
        is_active = request.form.get("is_active") == "on"

        if not name or not service_type:
            flash("Name and Service Type are required.", "error")
            return render_template("admin/service_form.html", service=svc)

        existing = Service.query.filter(
            Service.name == name, Service.id != service_id
        ).first()
        if existing:
            flash(f"Service '{name}' already exists.", "error")
            return render_template("admin/service_form.html", service=svc)

        svc.name = name
        svc.description = description
        svc.service_type = service_type
        svc.is_active = is_active
        db.session.commit()

        flash(f"Service '{name}' updated.", "success")
        return redirect(url_for("admin.service_list"))

    return render_template("admin/service_form.html", service=svc)


@admin_bp.route("/services/<int:service_id>/delete", methods=["POST"])
@admin_required
def service_delete(service_id):
    """Delete a service."""
    svc = Service.query.get_or_404(service_id)

    # Remove related subscriptions first
    Subscription.query.filter_by(service_id=svc.id).delete()
    db.session.delete(svc)
    db.session.commit()

    flash(f"Service '{svc.name}' deleted.", "success")
    return redirect(url_for("admin.service_list"))


# =============================================================================
# Blog Categories
# =============================================================================


@admin_bp.route("/blog/categories")
@admin_required
def blog_category_list():
    """List all blog categories."""
    categories = BlogCategory.query.order_by(BlogCategory.name).all()
    return render_template("admin/blog_categories.html", categories=categories)


@admin_bp.route("/blog/categories/create", methods=["GET", "POST"])
@admin_required
def blog_category_create():
    """Create a new blog category."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Category name is required.", "error")
            return render_template("admin/blog_category_form.html", category=None)

        slug = slugify(name)
        if BlogCategory.query.filter_by(slug=slug).first():
            flash(f"A category named '{name}' already exists.", "error")
            return render_template("admin/blog_category_form.html", category=None)

        cat = BlogCategory(name=name, slug=slug, description=description)
        db.session.add(cat)
        db.session.commit()

        flash(f"Category '{name}' created.", "success")
        return redirect(url_for("admin.blog_category_list"))

    return render_template("admin/blog_category_form.html", category=None)


@admin_bp.route("/blog/categories/<int:category_id>/edit", methods=["GET", "POST"])
@admin_required
def blog_category_edit(category_id):
    """Edit a blog category."""
    cat = BlogCategory.query.get_or_404(category_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Category name is required.", "error")
            return render_template("admin/blog_category_form.html", category=cat)

        slug = slugify(name)
        existing = BlogCategory.query.filter(
            BlogCategory.slug == slug, BlogCategory.id != category_id
        ).first()
        if existing:
            flash(f"A category named '{name}' already exists.", "error")
            return render_template("admin/blog_category_form.html", category=cat)

        cat.name = name
        cat.slug = slug
        cat.description = description
        db.session.commit()

        flash(f"Category '{name}' updated.", "success")
        return redirect(url_for("admin.blog_category_list"))

    return render_template("admin/blog_category_form.html", category=cat)


@admin_bp.route("/blog/categories/<int:category_id>/delete", methods=["POST"])
@admin_required
def blog_category_delete(category_id):
    """Delete a blog category. Posts in it become uncategorized, not deleted."""
    cat = BlogCategory.query.get_or_404(category_id)

    BlogPost.query.filter_by(category_id=cat.id).update({"category_id": None})
    db.session.delete(cat)
    db.session.commit()

    flash(f"Category '{cat.name}' deleted. Its posts are now uncategorized.", "success")
    return redirect(url_for("admin.blog_category_list"))


# =============================================================================
# Blog Posts
# =============================================================================


def _save_cover_image(file_storage):
    """Save an uploaded cover image and return its static-relative URL, or None."""
    if not file_storage or not file_storage.filename:
        return None

    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_COVER_EXTENSIONS:
        flash("Cover image must be a PNG, JPG, GIF, or WEBP file.", "error")
        return None

    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    upload_dir = os.path.join(current_app.static_folder, "uploads", "blog")
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return url_for("static", filename=f"uploads/blog/{filename}")


@admin_bp.route("/blog/posts")
@admin_required
def blog_post_list():
    """List all blog posts, optionally filtered by status."""
    status_filter = request.args.get("status", "").strip()
    query = BlogPost.query
    if status_filter in ("draft", "published"):
        query = query.filter_by(status=status_filter)
    posts = query.order_by(BlogPost.updated_at.desc()).all()
    return render_template(
        "admin/blog_posts.html", posts=posts, status_filter=status_filter
    )


@admin_bp.route("/blog/posts/create", methods=["GET", "POST"])
@admin_required
def blog_post_create():
    """Create a new blog post."""
    categories = BlogCategory.query.order_by(BlogCategory.name).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        excerpt = request.form.get("excerpt", "").strip()
        content = request.form.get("content", "").strip()
        status = request.form.get("status", "draft")
        category_id = request.form.get("category_id") or None

        if not title or not content:
            flash("Title and content are required.", "error")
            return render_template(
                "admin/blog_post_form.html", post=None, categories=categories
            )

        if status not in ("draft", "published"):
            status = "draft"

        slug = slugify(title)
        base_slug = slug
        suffix = 2
        while BlogPost.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        cover_image = _save_cover_image(request.files.get("cover_image"))

        post = BlogPost(
            title=title,
            slug=slug,
            excerpt=excerpt,
            content=content,
            status=status,
            category_id=int(category_id) if category_id else None,
            author_id=current_user.id,
            cover_image=cover_image or "",
            published_at=datetime.now(timezone.utc) if status == "published" else None,
        )
        db.session.add(post)
        db.session.commit()

        flash(f"Post '{title}' created.", "success")
        return redirect(url_for("admin.blog_post_list"))

    return render_template("admin/blog_post_form.html", post=None, categories=categories)


@admin_bp.route("/blog/posts/<int:post_id>/edit", methods=["GET", "POST"])
@admin_required
def blog_post_edit(post_id):
    """Edit a blog post."""
    post = BlogPost.query.get_or_404(post_id)
    categories = BlogCategory.query.order_by(BlogCategory.name).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        excerpt = request.form.get("excerpt", "").strip()
        content = request.form.get("content", "").strip()
        status = request.form.get("status", "draft")
        category_id = request.form.get("category_id") or None
        remove_cover = request.form.get("remove_cover") == "on"

        if not title or not content:
            flash("Title and content are required.", "error")
            return render_template(
                "admin/blog_post_form.html", post=post, categories=categories
            )

        if status not in ("draft", "published"):
            status = "draft"

        # Re-slug only if the title actually changed, to keep existing links stable.
        if title != post.title:
            slug = slugify(title)
            base_slug = slug
            suffix = 2
            while BlogPost.query.filter(BlogPost.slug == slug, BlogPost.id != post.id).first():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            post.slug = slug

        new_cover = _save_cover_image(request.files.get("cover_image"))
        if new_cover:
            post.cover_image = new_cover
        elif remove_cover:
            post.cover_image = ""

        was_published = post.status == "published"
        post.title = title
        post.excerpt = excerpt
        post.content = content
        post.status = status
        post.category_id = int(category_id) if category_id else None

        if status == "published" and not was_published:
            post.published_at = datetime.now(timezone.utc)
        elif status == "draft":
            post.published_at = None

        db.session.commit()

        flash(f"Post '{title}' updated.", "success")
        return redirect(url_for("admin.blog_post_list"))

    return render_template("admin/blog_post_form.html", post=post, categories=categories)


@admin_bp.route("/blog/posts/<int:post_id>/delete", methods=["POST"])
@admin_required
def blog_post_delete(post_id):
    """Delete a blog post."""
    post = BlogPost.query.get_or_404(post_id)
    title = post.title
    db.session.delete(post)
    db.session.commit()

    flash(f"Post '{title}' deleted.", "success")
    return redirect(url_for("admin.blog_post_list"))


@admin_bp.route("/blog/posts/<int:post_id>/toggle-status", methods=["POST"])
@admin_required
def blog_post_toggle_status(post_id):
    """Quickly publish a draft, or unpublish a live post."""
    post = BlogPost.query.get_or_404(post_id)

    if post.status == "published":
        post.status = "draft"
        post.published_at = None
        flash(f"'{post.title}' moved back to draft.", "success")
    else:
        post.status = "published"
        post.published_at = datetime.now(timezone.utc)
        flash(f"'{post.title}' published.", "success")

    db.session.commit()
    return redirect(url_for("admin.blog_post_list"))


# =============================================================================
# Admin Profile Settings
# =============================================================================


@admin_bp.route("/profile", methods=["GET", "POST"])
@admin_required
def profile():
    """Admin profile settings."""
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password and new_password == confirm_password:
            if len(new_password) < 4:
                flash("New password must be at least 4 characters.", "error")
                return redirect(url_for("admin.profile"))

            # Verify current password
            user = User.query.get(current_user.id)
            pw_hash = hashlib.sha256(
                (user.salt + current_password).encode("utf-8")
            ).hexdigest()
            if pw_hash != user.password_hash:
                flash("Current password is incorrect.", "error")
                return redirect(url_for("admin.profile"))

            # Update password
            new_salt = os.urandom(32).hex()
            new_hash = hashlib.sha256(
                (new_salt + new_password).encode("utf-8")
            ).hexdigest()
            user.password_hash = new_hash
            user.salt = new_salt
            db.session.commit()
            flash("Password changed successfully.", "success")
        else:
            flash("New passwords do not match or are empty.", "error")

        return redirect(url_for("admin.profile"))

    return render_template("admin/profile.html")