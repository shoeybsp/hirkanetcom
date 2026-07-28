import logging
import os
import sys
from flask import Flask, render_template, jsonify, redirect, url_for, flash, request, g
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.exceptions import HTTPException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from logging_config import configure_logging, install_request_logging
configure_logging()
logger = logging.getLogger(__name__)
from models import db, User, init_db
from auth.forms import LoginForm
from security import verify_password

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"), static_folder=os.path.join(BASE_DIR, "static"))
env = os.getenv("APP_ENV", "development").lower()
secret = os.getenv("SECRET_KEY")
if env == "production" and not secret:
    raise RuntimeError("SECRET_KEY is required in production")
app.config.update(
    SECRET_KEY=secret or "development-only-secret",
    WTF_CSRF_TIME_LIMIT=3600,
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=env == "production",
    SESSION_COOKIE_SAMESITE="Lax",
)
init_db(app)
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

@app.template_filter("nl2p")
def nl2p(text):
    from markupsafe import Markup, escape
    if not text: return Markup("")
    paragraphs=[p.strip() for p in text.replace("\r\n","\n").split("\n\n") if p.strip()]
    return Markup("".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs))

@app.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("main.home"))
    form=LoginForm()
    if form.validate_on_submit():
        username=form.username.data.strip().lower(); password=form.password.data
        user=User.query.filter_by(username=username).first()
        if user is not None and verify_password(user,password):
            db.session.commit()
            login_user(user)
            logger.info("Login succeeded", extra={"event_type":"authentication_success","user_id":str(user.id),"username":user.username})
            next_page=request.args.get("next")
            if next_page and next_page.startswith("/") and not next_page.startswith("//"): return redirect(next_page)
            return redirect(url_for("main.home"))
        logger.warning("Login failed", extra={"event_type":"authentication_failure","username":username,"source_ip":request.remote_addr})
        flash("Invalid username or password.","error")
        return render_template("login.html",form=form),401
    return render_template("login.html",form=form)

@app.route("/logout", methods=["GET", "POST"])
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

@app.errorhandler(404)
def not_found(error): return render_template("main/404.html"),404
@app.errorhandler(Exception)
def unhandled(error):
    if isinstance(error,HTTPException): return error
    logger.exception("Unhandled request exception", extra={"event_type":"unhandled_exception","request_id":getattr(g,"request_id",None)})
    return jsonify({"error":"internal_server_error","request_id":getattr(g,"request_id",None)}),500

logger.info("Application initialized", extra={"event_type":"application_start","base_dir":BASE_DIR})
if __name__ == "__main__": app.run(debug=env != "production", host="127.0.0.1")
