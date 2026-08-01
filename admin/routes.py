import os
import logging
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
from database_transactions import commit_transaction
from security import hash_password, verify_password
from validation import ValidationError
from validation.admin import (
    validate_blog_post,
    validate_category,
    validate_password_change,
    validate_service,
    validate_subscription_ids,
    validate_user,
)
from validation.uploads import validate_cover_image

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)


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
        try:
            values = validate_user(request.form, password_required=True)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/user_form.html", user=None)
        username, password, role = values.username, values.password, values.role

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash(f"User '{username}' already exists.", "error")
            return render_template("admin/user_form.html", user=None)
        user = User(username=username, password_hash=hash_password(password), salt="", role=role)
        db.session.add(user)
        commit_transaction("admin database change")
        logger.info("User created", extra={"event_type":"audit_user_created","actor_user_id":str(current_user.id),"target_user_id":str(user.id),"role":role})

        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("admin.user_list"))

    return render_template("admin/user_form.html", user=None)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    """Edit a user."""
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            values = validate_user(request.form, password_required=False)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/user_form.html", user=user)
        username, password, role = values.username, values.password, values.role

        # Check if username is taken by another user
        existing = User.query.filter(User.username == username, User.id != user_id).first()
        if existing:
            flash(f"Username '{username}' is already taken.", "error")
            return render_template("admin/user_form.html", user=user)

        user.username = username
        user.role = role

        if password:
            user.password_hash = hash_password(password)
            user.salt = ""

        commit_transaction("admin database change")
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

    target_id=str(user.id); target_username=user.username
    db.session.delete(user)
    commit_transaction("admin database change")
    logger.info("User deleted", extra={"event_type":"audit_user_deleted","actor_user_id":str(current_user.id),"target_user_id":target_id,"target_username":target_username})

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
        try:
            selected_service_ids = validate_subscription_ids(
                request.form.getlist("services"),
                allowed_ids={service.id for service in services},
            )
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/user_subscriptions.html", user=user, services=services)

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

        commit_transaction("admin database change")
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
        try:
            values = validate_service(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/service_form.html", service=None)
        name = values.name
        description = values.description
        service_type = values.service_type
        is_active = values.is_active

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
        commit_transaction("admin database change")

        flash(f"Service '{name}' created.", "success")
        return redirect(url_for("admin.service_list"))

    return render_template("admin/service_form.html", service=None)


@admin_bp.route("/services/<int:service_id>/edit", methods=["GET", "POST"])
@admin_required
def service_edit(service_id):
    """Edit a service."""
    svc = Service.query.get_or_404(service_id)

    if request.method == "POST":
        try:
            values = validate_service(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/service_form.html", service=svc)
        name = values.name
        description = values.description
        service_type = values.service_type
        is_active = values.is_active

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
        commit_transaction("admin database change")

        flash(f"Service '{name}' updated.", "success")
        return redirect(url_for("admin.service_list"))

    return render_template("admin/service_form.html", service=svc)


@admin_bp.route("/services/<int:service_id>/delete", methods=["POST"])
@admin_required
def service_delete(service_id):
    """Delete a service."""
    svc = Service.query.get_or_404(service_id)

    db.session.delete(svc)
    commit_transaction("admin database change")

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
        try:
            values = validate_category(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/blog_category_form.html", category=None)
        name, description = values.name, values.description

        slug = slugify(name)
        if BlogCategory.query.filter_by(slug=slug).first():
            flash(f"A category named '{name}' already exists.", "error")
            return render_template("admin/blog_category_form.html", category=None)

        cat = BlogCategory(name=name, slug=slug, description=description)
        db.session.add(cat)
        commit_transaction("admin database change")

        flash(f"Category '{name}' created.", "success")
        return redirect(url_for("admin.blog_category_list"))

    return render_template("admin/blog_category_form.html", category=None)


@admin_bp.route("/blog/categories/<int:category_id>/edit", methods=["GET", "POST"])
@admin_required
def blog_category_edit(category_id):
    """Edit a blog category."""
    cat = BlogCategory.query.get_or_404(category_id)

    if request.method == "POST":
        try:
            values = validate_category(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/blog_category_form.html", category=cat)
        name, description = values.name, values.description

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
        commit_transaction("admin database change")

        flash(f"Category '{name}' updated.", "success")
        return redirect(url_for("admin.blog_category_list"))

    return render_template("admin/blog_category_form.html", category=cat)


@admin_bp.route("/blog/categories/<int:category_id>/delete", methods=["POST"])
@admin_required
def blog_category_delete(category_id):
    """Delete a blog category. Posts in it become uncategorized, not deleted."""
    cat = BlogCategory.query.get_or_404(category_id)

    db.session.delete(cat)
    commit_transaction("admin database change")

    flash(f"Category '{cat.name}' deleted. Its posts are now uncategorized.", "success")
    return redirect(url_for("admin.blog_category_list"))


# =============================================================================
# Blog Posts
# =============================================================================


def _save_cover_image(file_storage):
    """Validate and save an uploaded cover image."""
    ext = validate_cover_image(file_storage)
    if ext is None:
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
        try:
            values = validate_blog_post(
                request.form, allowed_category_ids={category.id for category in categories}
            )
            cover_image = _save_cover_image(request.files.get("cover_image"))
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/blog_post_form.html", post=None, categories=categories)
        title, excerpt, content = values.title, values.excerpt, values.content
        status, category_id = values.status, values.category_id

        slug = slugify(title)
        base_slug = slug
        suffix = 2
        while BlogPost.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        post = BlogPost(
            title=title,
            slug=slug,
            excerpt=excerpt,
            content=content,
            status=status,
            category_id=category_id,
            author_id=current_user.id,
            cover_image=cover_image or "",
            published_at=datetime.now(timezone.utc) if status == "published" else None,
        )
        db.session.add(post)
        commit_transaction("admin database change")

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
        try:
            values = validate_blog_post(
                request.form, allowed_category_ids={category.id for category in categories}
            )
            new_cover = _save_cover_image(request.files.get("cover_image"))
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/blog_post_form.html", post=post, categories=categories)
        title, excerpt, content = values.title, values.excerpt, values.content
        status, category_id, remove_cover = values.status, values.category_id, values.remove_cover

        # Re-slug only if the title actually changed, to keep existing links stable.
        if title != post.title:
            slug = slugify(title)
            base_slug = slug
            suffix = 2
            while BlogPost.query.filter(BlogPost.slug == slug, BlogPost.id != post.id).first():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            post.slug = slug

        if new_cover:
            post.cover_image = new_cover
        elif remove_cover:
            post.cover_image = ""

        was_published = post.status == "published"
        post.title = title
        post.excerpt = excerpt
        post.content = content
        post.status = status
        post.category_id = category_id

        if status == "published" and not was_published:
            post.published_at = datetime.now(timezone.utc)
        elif status == "draft":
            post.published_at = None

        commit_transaction("admin database change")

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
    commit_transaction("admin database change")

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

    commit_transaction("admin database change")
    return redirect(url_for("admin.blog_post_list"))


# =============================================================================
# Admin Profile Settings
# =============================================================================


@admin_bp.route("/profile", methods=["GET", "POST"])
@admin_required
def profile():
    """Admin profile settings."""
    if request.method == "POST":
        try:
            current_password, new_password = validate_password_change(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return redirect(url_for("admin.profile"))
        user = db.session.get(User, current_user.id)
        if not verify_password(user, current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("admin.profile"))
        user.password_hash = hash_password(new_password)
        user.salt = ""
        commit_transaction("admin database change")
        flash("Password changed successfully.", "success")

        return redirect(url_for("admin.profile"))

    return render_template("admin/profile.html")