import logging
import uuid

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
)
from flask_login import login_required, current_user
from models import db, User, Service, Subscription, Device, DeviceAssignment
from database_transactions import commit_transaction
from security import hash_password, verify_password
from secret_crypto import encrypt_secret
from collectors.sync_service import DeviceSyncError, run_device_sync
from validation import ValidationError
from validation.admin import (
    validate_device,
    validate_device_assignment_user_ids,
    validate_password_change,
    validate_service,
    validate_subscription_ids,
    validate_user,
)

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
    device_count = Device.query.count()
    return render_template(
        "admin/dashboard.html",
        user_count=user_count,
        service_count=service_count,
        subscription_count=subscription_count,
        device_count=device_count,
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
# Device Inventory Management
# =============================================================================


@admin_bp.route("/devices")
@admin_required
def device_list():
    """List all registered devices."""
    devices = Device.query.order_by(Device.name).all()
    return render_template("admin/device_list.html", devices=devices)


@admin_bp.route("/devices/create", methods=["GET", "POST"])
@admin_required
def device_create():
    """Register a new device."""
    if request.method == "POST":
        try:
            values = validate_device(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/device_form.html", device=None)

        existing = Device.query.filter_by(name=values.name).first()
        if existing:
            flash(f"Device '{values.name}' already exists.", "error")
            return render_template("admin/device_form.html", device=None)

        device = Device(
            name=values.name,
            device_type=values.device_type,
            api_host=values.api_host,
            api_scheme=values.api_scheme,
            vdom=values.vdom,
            verify_ssl=values.verify_ssl,
            timeout_seconds=values.timeout_seconds,
            skip_monitor_routes=values.skip_monitor_routes,
            keep_snapshots=values.keep_snapshots,
            is_active=values.is_active,
            # Each device gets its own isolated snapshot directory, keyed by
            # a random id rather than the (renameable) device name.
            data_dir=f"data/devices/{uuid.uuid4().hex}",
            api_key_encrypted=encrypt_secret(values.api_key),
            auth_username_encrypted=encrypt_secret(values.auth_username),
            auth_password_encrypted=encrypt_secret(values.auth_password),
        )
        db.session.add(device)
        commit_transaction("admin database change")
        logger.info(
            "Device created",
            extra={
                "event_type": "audit_device_created",
                "actor_user_id": str(current_user.id),
                "device_id": str(device.id),
                "device_name": device.name,
            },
        )

        if not values.api_key:
            flash(
                f"Device '{device.name}' created. Add an API key before syncing it.",
                "success",
            )
        else:
            flash(f"Device '{device.name}' created.", "success")
        return redirect(url_for("admin.device_list"))

    return render_template("admin/device_form.html", device=None)


@admin_bp.route("/devices/<int:device_id>/edit", methods=["GET", "POST"])
@admin_required
def device_edit(device_id):
    """Edit a device's connection settings and credentials."""
    device = Device.query.get_or_404(device_id)

    if request.method == "POST":
        try:
            values = validate_device(request.form)
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            return render_template("admin/device_form.html", device=device)

        existing = Device.query.filter(
            Device.name == values.name, Device.id != device_id
        ).first()
        if existing:
            flash(f"Device '{values.name}' already exists.", "error")
            return render_template("admin/device_form.html", device=device)

        device.name = values.name
        device.device_type = values.device_type
        device.api_host = values.api_host
        device.api_scheme = values.api_scheme
        device.vdom = values.vdom
        device.verify_ssl = values.verify_ssl
        device.timeout_seconds = values.timeout_seconds
        device.skip_monitor_routes = values.skip_monitor_routes
        device.keep_snapshots = values.keep_snapshots
        device.is_active = values.is_active

        # Credential fields are write-only and never rendered back into the
        # form; a blank field means "keep the currently stored value",
        # matching the admin password-change pattern used elsewhere.
        if values.api_key:
            device.api_key_encrypted = encrypt_secret(values.api_key)
        if values.auth_username:
            device.auth_username_encrypted = encrypt_secret(values.auth_username)
        if values.auth_password:
            device.auth_password_encrypted = encrypt_secret(values.auth_password)

        commit_transaction("admin database change")
        logger.info(
            "Device updated",
            extra={
                "event_type": "audit_device_updated",
                "actor_user_id": str(current_user.id),
                "device_id": str(device.id),
            },
        )

        flash(f"Device '{device.name}' updated.", "success")
        return redirect(url_for("admin.device_list"))

    return render_template("admin/device_form.html", device=device)


@admin_bp.route("/devices/<int:device_id>/delete", methods=["POST"])
@admin_required
def device_delete(device_id):
    """Delete a device from the inventory.

    This only removes the database record (and, via cascade, any client
    assignments for it). Collected snapshot files under the device's
    data_dir are left on disk untouched.
    """
    device = Device.query.get_or_404(device_id)
    name = device.name
    device_id_str = str(device.id)

    db.session.delete(device)
    commit_transaction("admin database change")
    logger.info(
        "Device deleted",
        extra={
            "event_type": "audit_device_deleted",
            "actor_user_id": str(current_user.id),
            "device_id": device_id_str,
            "device_name": name,
        },
    )

    flash(f"Device '{name}' deleted. Its collected snapshot data on disk was not removed.", "success")
    return redirect(url_for("admin.device_list"))


@admin_bp.route("/devices/<int:device_id>/sync", methods=["POST"])
@admin_required
def device_sync(device_id):
    """Run the collector for a single device and record the outcome."""
    device = Device.query.get_or_404(device_id)

    if not device.is_active:
        flash(f"Device '{device.name}' is inactive. Activate it before syncing.", "error")
        return redirect(url_for("admin.device_list"))

    logger.info(
        "Device sync requested",
        extra={
            "event_type": "device_sync_requested",
            "actor_user_id": str(current_user.id),
            "device_id": str(device.id),
        },
    )

    try:
        result = run_device_sync(device)
    except DeviceSyncError as exc:
        # last_sync_* fields were updated by the sync service; persist them
        # so the failure is visible in the device list.
        commit_transaction("admin database change")
        flash(f"Sync failed for '{device.name}': {exc}", "error")
        return redirect(url_for("admin.device_list"))

    commit_transaction("admin database change")
    counts = result["record_counts"]
    flash(
        f"Synced '{device.name}': {counts.get('policies.json', 0)} policies, "
        f"{counts.get('addresses.json', 0)} addresses, "
        f"{counts.get('services.json', 0)} services, "
        f"{counts.get('routes.json', 0)} routes, "
        f"{counts.get('interfaces.json', 0)} interfaces.",
        "success",
    )
    return redirect(url_for("admin.device_list"))


@admin_bp.route("/devices/<int:device_id>/assignments", methods=["GET", "POST"])
@admin_required
def device_assignments(device_id):
    """Manage which client users may evaluate policies against this device."""
    device = Device.query.get_or_404(device_id)
    clients = User.query.filter_by(role="client").order_by(User.username).all()

    if request.method == "POST":
        try:
            selected_user_ids = validate_device_assignment_user_ids(
                request.form.getlist("users"),
                allowed_ids={user.id for user in clients},
            )
        except ValidationError as exc:
            flash(exc.as_text(), "error")
            assigned_ids = {a.user_id for a in device.assignments}
            return render_template(
                "admin/device_assignments.html",
                device=device,
                clients=clients,
                assigned_ids=assigned_ids,
            )

        # Remove unselected assignments
        for assignment in device.assignments:
            if assignment.user_id not in selected_user_ids:
                db.session.delete(assignment)

        # Add new assignments
        existing_ids = {a.user_id for a in device.assignments}
        for user_id in selected_user_ids:
            if user_id not in existing_ids:
                db.session.add(
                    DeviceAssignment(user_id=user_id, device_id=device.id, is_active=True)
                )

        commit_transaction("admin database change")
        logger.info(
            "Device client access updated",
            extra={
                "event_type": "audit_device_assignments_updated",
                "actor_user_id": str(current_user.id),
                "device_id": str(device.id),
                "assigned_user_count": len(selected_user_ids),
            },
        )

        flash(f"Client access for '{device.name}' updated.", "success")
        return redirect(url_for("admin.device_list"))

    assigned_ids = {a.user_id for a in device.assignments}
    return render_template(
        "admin/device_assignments.html",
        device=device,
        clients=clients,
        assigned_ids=assigned_ids,
    )


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