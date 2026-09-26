from datetime import datetime, timezone

from flask import Blueprint, redirect, url_for
from flask_login import current_user

main_bp = Blueprint("main", __name__)


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
    """Root URL redirects to the appropriate dashboard or login."""
    if current_user.is_authenticated:
        return _role_redirect()
    return redirect(url_for("login"))
