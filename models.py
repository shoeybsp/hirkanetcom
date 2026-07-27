import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    salt = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="client")  # "admin" or "client"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    subscriptions = db.relationship("Subscription", back_populates="user", lazy="dynamic")

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    service_type = db.Column(db.String(100), nullable=False)  # e.g. "policy_evaluation"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    subscriptions = db.relationship("Subscription", back_populates="service", lazy="dynamic")

    def __repr__(self):
        return f"<Service {self.name} ({self.service_type})>"


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    start_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    end_date = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="subscriptions")
    service = db.relationship("Service", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription user={self.user_id} service={self.service_id} active={self.is_active}>"


def slugify(value):
    """Turn a title into a URL-safe slug (no external deps required)."""
    import re

    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value).strip("-")
    return value or "post"


class BlogCategory(db.Model):
    __tablename__ = "blog_categories"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    posts = db.relationship("BlogPost", back_populates="category", lazy="dynamic")

    @property
    def published_count(self):
        return self.posts.filter_by(status="published").count()

    def __repr__(self):
        return f"<BlogCategory {self.name}>"


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False, index=True)
    excerpt = db.Column(db.String(400), default="")
    content = db.Column(db.Text, nullable=False, default="")
    cover_image = db.Column(db.String(300), default="")  # path under /static, or empty
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | published
    category_id = db.Column(db.Integer, db.ForeignKey("blog_categories.id"), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    published_at = db.Column(db.DateTime, nullable=True)

    category = db.relationship("BlogCategory", back_populates="posts")
    author = db.relationship("User")

    @property
    def is_published(self):
        return self.status == "published"

    @property
    def reading_minutes(self):
        words = len((self.content or "").split())
        return max(1, round(words / 200))

    def __repr__(self):
        return f"<BlogPost {self.title!r} ({self.status})>"


def _default_database_url():
    """Return a local SQLite database path when no database URL is configured."""
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    return f"sqlite:///{os.path.join(repo_dir, 'fortigate_policy.db')}"


def _normalize_database_url(database_url):
    """Normalize SQLite URLs to a form accepted by SQLAlchemy."""
    if not database_url.startswith("sqlite"):
        return database_url

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return database_url

    if not parsed.path or parsed.path == ":memory:" or parsed.path == "/:memory:":
        return "sqlite:///:memory:"

    if os.path.isabs(parsed.path):
        return f"sqlite:////{parsed.path.lstrip('/')}"

    return f"sqlite:///{parsed.path}"


def _ensure_database_path(database_url):
    """Create parent directories for SQLite database files before connecting."""
    if not database_url.startswith("sqlite"):
        return

    parsed = urlparse(database_url)
    database_path = parsed.path
    if not database_path or database_path == ":memory:" or database_path == "/:memory:":
        return

    parent_dir = os.path.dirname(database_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def init_db(app):
    """Initialize the database and create tables.

    Retries the initial connection with backoff. In Docker Compose, the app
    container can start importing before Postgres is fully ready to accept
    connections even with a healthcheck-gated `depends_on`, and a single
    failed connection here would otherwise crash the whole container.
    """
    import time
    from sqlalchemy.exc import OperationalError

    database_url = os.environ.get("DATABASE_URL", _default_database_url())
    database_url = _normalize_database_url(database_url)
    _ensure_database_path(database_url)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    max_attempts = 10
    delay_seconds = 2
    for attempt in range(1, max_attempts + 1):
        try:
            with app.app_context():
                db.create_all()
                _seed_defaults()
            break
        except OperationalError as exc:
            if attempt == max_attempts:
                raise
            print(
                f"Database not ready yet (attempt {attempt}/{max_attempts}): {exc}. "
                f"Retrying in {delay_seconds}s...",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)


def _seed_defaults():
    """Seed default admin user and default services if they don't exist."""
    import hashlib
    import os as _os

    # Seed default admin
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        salt = _os.urandom(32).hex()
        pw_hash = hashlib.sha256((salt + "admin").encode("utf-8")).hexdigest()
        admin = User(
            username="admin",
            password_hash=pw_hash,
            salt=salt,
            role="admin",
        )
        db.session.add(admin)

    # Seed default services
    default_services = [
        {
            "name": "Policy Evaluation",
            "description": "Evaluate FortiGate firewall policies for new access requests",
            "service_type": "policy_evaluation",
        },
    ]
    for svc_data in default_services:
        existing = Service.query.filter_by(service_type=svc_data["service_type"]).first()
        if existing is None:
            svc = Service(**svc_data)
            db.session.add(svc)

    db.session.commit()
    _seed_blog_defaults(admin)


def _seed_blog_defaults(admin_user):
    """Seed a few illustrative blog categories and posts on first run only.

    These are placeholder posts so the public blog isn't empty out of the box.
    Replace or delete them from the admin Blog Posts screen.
    """
    if BlogCategory.query.count() > 0 or BlogPost.query.count() > 0:
        return

    categories = [
        BlogCategory(
            name="Cyber Security",
            slug="cyber-security",
            description="Threat detection, zero trust, and defensive strategy.",
        ),
        BlogCategory(
            name="Application Delivery",
            slug="application-delivery",
            description="Load balancing, uptime, and performance at scale.",
        ),
        BlogCategory(
            name="Compliance",
            slug="compliance",
            description="Policy hygiene, audits, and least-privilege access.",
        ),
    ]
    for c in categories:
        db.session.add(c)
    db.session.flush()

    now = datetime.now(timezone.utc)
    posts = [
        {
            "title": "Why Least-Privilege Firewall Rules Still Get Ignored",
            "category": categories[2],
            "excerpt": "Most rule bases grow one exception at a time. Here's how that drift happens, and what a periodic policy review should actually check for.",
            "content": (
                "Every firewall rule base starts clean. Somewhere around month six, "
                "the first \"just for now\" rule gets added to unblock a deployment, "
                "and it never gets removed.\n\n"
                "The pattern is familiar to anyone who has audited a production rule "
                "set: broad source objects, services opened for testing that were "
                "never scoped back down, and destination groups that quietly absorbed "
                "new subnets over time. None of it looks wrong in isolation. Together, "
                "it adds up to a policy set that grants far more access than any "
                "single request actually needs.\n\n"
                "A useful habit is to evaluate new access requests against the "
                "existing rule base before writing a new rule at all. If an existing "
                "policy already covers the source, destination, and service with a "
                "tight match, extend that rule instead of creating another one. If "
                "nothing covers it cleanly, that's a signal the request needs its own "
                "narrowly scoped policy \u2014 not a broader version of an existing one.\n\n"
                "The goal isn't zero new rules. It's making sure every rule that "
                "exists still maps to a real, current need."
            ),
        },
        {
            "title": "Application Delivery Is a Security Control, Not Just a Performance One",
            "category": categories[1],
            "excerpt": "Load balancers and ADCs sit in front of everything. Treating them as pure performance infrastructure leaves an obvious layer under-protected.",
            "content": (
                "It's easy to think of application delivery controllers as plumbing: "
                "the thing that spreads load across servers and keeps latency down. "
                "That framing misses what an ADC actually sees \u2014 every request, "
                "to every backend, before anything else touches it.\n\n"
                "That vantage point makes it one of the more useful places to enforce "
                "security policy, not despite being infrastructure, but because of it. "
                "TLS termination, request validation, rate limiting, and basic bot "
                "filtering can all happen at the delivery layer, before a malformed or "
                "malicious request ever reaches an application server.\n\n"
                "The practical implication is that ADC configuration deserves the "
                "same review discipline as firewall policy. A load balancer rule that "
                "forwards traffic to an internal service without validating headers, "
                "or a health check endpoint left open to the internet, is a gap in the "
                "same way an overly broad firewall rule is.\n\n"
                "Uptime and security aren't competing priorities here. The layer that "
                "keeps an application fast is also the layer best positioned to keep "
                "it safe."
            ),
        },
        {
            "title": "What Zero Trust Actually Changes About Day-to-Day Access Requests",
            "category": categories[0],
            "excerpt": "Zero trust gets discussed as an architecture. In practice, it shows up as a different default answer to a very ordinary question: should this be allowed?",
            "content": (
                "Zero trust is often described in terms of architecture diagrams: "
                "micro-segmentation, identity-aware proxies, continuous verification. "
                "Those are real components, but the day-to-day change is simpler than "
                "the diagrams suggest.\n\n"
                "Under a perimeter model, the default answer to \"can this internal "
                "service reach that internal service\" is often yes, unless something "
                "explicitly blocks it. Under zero trust, the default flips: the answer "
                "is no, until a specific policy grants exactly that path, for exactly "
                "that purpose.\n\n"
                "That flip changes how access requests get handled operationally. "
                "Instead of assuming connectivity and only intervening when something "
                "breaks, every new source-destination-service combination gets "
                "evaluated against what's actually permitted. Either an existing "
                "policy already covers it at the right scope, or a new, narrowly "
                "defined one needs to be created.\n\n"
                "None of this requires ripping out existing infrastructure on day "
                "one. It starts as a discipline: treat every request as something to "
                "verify, not something to assume."
            ),
        },
    ]

    for i, p in enumerate(posts):
        post = BlogPost(
            title=p["title"],
            slug=slugify(p["title"]),
            excerpt=p["excerpt"],
            content=p["content"],
            status="published",
            category=p["category"],
            author=admin_user,
            published_at=now,
        )
        db.session.add(post)

    db.session.commit()