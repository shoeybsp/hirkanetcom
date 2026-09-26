import logging
import os
import sys

import click
from flask import Flask, render_template, jsonify, redirect, url_for, flash, request, g
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from logging_config import configure_logging, install_request_logging
configure_logging()
logger = logging.getLogger(__name__)
from models import db, User, init_db, seed_defaults
from auth.forms import LoginForm
from security import verify_password
from auth.rate_limit import check_login_allowed, clear_login_failures, record_login_failure
from secret_utils import read_secret
from database_transactions import (
    DatabaseTransactionError,
    commit_transaction,
)

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"), static_folder=os.path.join(BASE_DIR, "static"))
env = os.getenv("APP_ENV", "development").lower()
secret = read_secret("SECRET_KEY", required=env == "production")
trusted_hosts = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "hirkanet.com,www.hirkanet.com,localhost,127.0.0.1").split(",")
    if host.strip()
]
app.config.update(
    SECRET_KEY=secret or "development-only-secret",
    WTF_CSRF_TIME_LIMIT=3600,
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
    LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS=int(os.getenv("LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS", "5")),
    LOGIN_RATE_LIMIT_IP_ATTEMPTS=int(os.getenv("LOGIN_RATE_LIMIT_IP_ATTEMPTS", "20")),
    LOGIN_RATE_LIMIT_WINDOW_SECONDS=int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")),
    LOGIN_RATE_LIMIT_BLOCK_SECONDS=int(os.getenv("LOGIN_RATE_LIMIT_BLOCK_SECONDS", "900")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=env == "production",
    SESSION_COOKIE_SAMESITE="Lax",
    PREFERRED_URL_SCHEME="https" if env == "production" else "http",
    TRUSTED_HOSTS=trusted_hosts,
)

# Trust forwarding headers only when Hirkanet is behind the documented,
# single-hop reverse proxy. Never enable this for a directly exposed app.
if os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes", "on"}:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
init_db(app)
migrate = Migrate(app, db, compare_type=True, render_as_batch=True)
csrf = CSRFProtect(app)
install_request_logging(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access this page."
login_manager.login_message_category = "success"
@login_manager.user_loader
def load_user(user_id):
    try: return db.session.get(User, int(user_id))
    except (TypeError, ValueError): return None

from admin.routes import admin_bp
from client.routes import client_bp
from main.routes import main_bp
app.register_blueprint(admin_bp); app.register_blueprint(client_bp); app.register_blueprint(main_bp)


@app.errorhandler(DatabaseTransactionError)
def handle_database_transaction_error(error):
    """Return a clean response after the transaction helper has rolled back."""
    logger.error(
        "Database operation failed",
        extra={
            "event_type": "database_operation_failure",
            "operation": error.operation,
            "status_code": error.status_code,
        },
    )
    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify({"error": error.public_message}), error.status_code
    return (
        render_template(
            "main/database_error.html",
            message=error.public_message,
        ),
        error.status_code,
    )


@app.cli.command("seed-defaults")
def seed_defaults_command():
    """Create the optional bootstrap administrator and default content."""
    seed_defaults()
    print("Hirkanet default data is present.")


@app.template_filter("nl2p")
def nl2p(text):
    from markupsafe import Markup, escape
    if not text: return Markup("")
    paragraphs=[p.strip() for p in text.replace("\r\n","\n").split("\n\n") if p.strip()]
    return Markup("".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        password = form.password.data
        source_ip = request.remote_addr or "unknown"

        decision = check_login_allowed(username, source_ip)
        if not decision.allowed:
            logger.warning(
                "Login rate limit blocked request",
                extra={
                    "event_type": "authentication_rate_limited",
                    "username": username,
                    "source_ip": source_ip,
                    "rate_limit_scope": decision.scope,
                    "retry_after_seconds": decision.retry_after,
                },
            )
            response = render_template(
                "login.html",
                form=form,
                rate_limited=True,
                retry_after=decision.retry_after,
            )
            return response, 429, {"Retry-After": str(decision.retry_after)}

        user = User.query.filter_by(username=username).first()
        if user is not None and verify_password(user, password):
            commit_transaction("upgrade authenticated user credentials")
            clear_login_failures(username)
            login_user(user)
            logger.info(
                "Login succeeded",
                extra={
                    "event_type": "authentication_success",
                    "user_id": str(user.id),
                    "username": user.username,
                },
            )
            next_page = request.args.get("next")
            if next_page and next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("main.home"))

        failure_decision = record_login_failure(username, source_ip)
        logger.warning(
            "Login failed",
            extra={
                "event_type": "authentication_failure",
                "username": username,
                "source_ip": source_ip,
                "rate_limit_scope": failure_decision.scope,
            },
        )
        flash("Invalid username or password.", "error")
        headers = {}
        status_code = 401
        if not failure_decision.allowed:
            status_code = 429
            headers["Retry-After"] = str(failure_decision.retry_after)
        return render_template("login.html", form=form), status_code, headers

    return render_template("login.html", form=form)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    user_id=str(current_user.id); logout_user()
    logger.info("Logout succeeded", extra={"event_type":"logout","user_id":user_id})
    flash("You have been signed out.","info"); return redirect(url_for("login"))

@app.route("/livez")
def livez(): return jsonify({"status":"ok"})
@app.route("/readyz")
def readyz():
    try:
        db.session.execute(db.text("SELECT 1")); return jsonify({"status":"ready"})
    except Exception:
        logger.exception("Readiness check failed", extra={"event_type":"readiness_failure"})
        return jsonify({"status":"not_ready"}),503
@app.route("/healthz")
def healthz(): return readyz()

@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    logger.warning(
        "CSRF validation failed",
        extra={
            "event_type": "csrf_validation_failure",
            "reason": error.description,
            "source_ip": request.remote_addr,
        },
    )
    if request.accept_mimetypes.best == "application/json":
        return jsonify({"error": "csrf_validation_failed", "message": error.description}), 400
    return render_template("main/400.html", message="The form expired or was submitted from an invalid page. Please try again."), 400

@app.errorhandler(404)
def not_found(error): return render_template("main/404.html"),404
@app.errorhandler(Exception)
def unhandled(error):
    if isinstance(error,HTTPException): return error
    logger.exception("Unhandled request exception", extra={"event_type":"unhandled_exception","request_id":getattr(g,"request_id",None)})
    return jsonify({"error":"internal_server_error","request_id":getattr(g,"request_id",None)}),500

logger.info("Application initialized", extra={"event_type":"application_start","base_dir":BASE_DIR})
if __name__ == "__main__": app.run(debug=env != "production", host="127.0.0.1")
