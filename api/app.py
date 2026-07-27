import os
import sys
from flask import (
    Flask,
    render_template,
    jsonify,
    redirect,
    url_for,
    flash,
    request,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
import hashlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from models import db, User, init_db
from auth.forms import LoginForm

print("Base directory:", BASE_DIR)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# -- Secret key ---------------------------------------------------------------
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "dev-secret-change-in-production-abc123xyz",
)
app.config["WTF_CSRF_TIME_LIMIT"] = None

# -- Initialize database ------------------------------------------------------
init_db(app)

# -- Flask-Login setup --------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access this page."
login_manager.login_message_category = "success"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


# -- Register blueprints ------------------------------------------------------
from admin.routes import admin_bp
from client.routes import client_bp
from main.routes import main_bp

app.register_blueprint(admin_bp)
app.register_blueprint(client_bp)
app.register_blueprint(main_bp)


# -- Template filters ----------------------------------------------------------
@app.template_filter("nl2p")
def nl2p(text):
    """Turn blank-line-separated plain text into escaped <p> paragraphs.

    Content is still autoescaped per-line (Markup.escape), so this is safe to
    use with admin-authored blog content without allowing arbitrary HTML.
    """
    from markupsafe import Markup, escape

    if not text:
        return Markup("")
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    html = "".join(
        f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs
    )
    return Markup(html)

# ============================================================================
#  AUTHENTICATION ROUTES
# ============================================================================


@app.route("/login", methods=["GET", "POST"])
def login():
    """Render login form and authenticate."""
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        password = form.password.data

        user = User.query.filter_by(username=username).first()
        if user is not None:
            pw_hash = hashlib.sha256(
                (user.salt + password).encode("utf-8")
            ).hexdigest()
            if pw_hash == user.password_hash:
                login_user(user)
                next_page = request.args.get("next")
                if next_page and next_page.startswith("/"):
                    return redirect(next_page)
                return redirect(url_for("main.home"))

        flash("Invalid username or password.", "error")
        return render_template("login.html", form=form), 401

    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("login"))


# ============================================================================
#  HEALTH CHECK
# ============================================================================


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ============================================================================
#  ERROR PAGES
# ============================================================================


@app.errorhandler(404)
def not_found(error):
    return render_template("main/404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")