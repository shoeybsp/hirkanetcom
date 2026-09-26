import logging
import os
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from secret_utils import read_secret

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Make SQLite enforce FOREIGN KEY constraints, including ON DELETE
    CASCADE/SET NULL, per-connection.

    SQLite ignores these constraints by default unless this pragma is set on
    every connection. Postgres (used in production, per docker-compose)
    enforces them natively regardless, so this only matters for local
    development and tests that use the sqlite:// fallback URL.
    """
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
logger = logging.getLogger(__name__)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('admin', 'client')",
            name="ck_users_role",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(512), nullable=False)
    salt = db.Column(db.String(64), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="client")  # "admin" or "client"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    subscriptions = db.relationship(
        "Subscription",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    device_assignments = db.relationship(
        "DeviceAssignment",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class LoginRateLimit(db.Model):
    """Failed-login counters shared by all application workers."""

    __tablename__ = "login_rate_limits"
    __table_args__ = (
        db.UniqueConstraint(
            "scope",
            "identifier_hash",
            name="uq_login_rate_limits_scope_identifier",
        ),
        db.CheckConstraint(
            "scope IN ('username', 'ip')",
            name="ck_login_rate_limits_scope",
        ),
        db.Index("ix_login_rate_limits_blocked_until", "blocked_until_epoch"),
        db.Index("ix_login_rate_limits_updated_at", "updated_at_epoch"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scope = db.Column(db.String(20), nullable=False)
    identifier_hash = db.Column(db.String(64), nullable=False)
    window_started_epoch = db.Column(db.BigInteger, nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    blocked_until_epoch = db.Column(db.BigInteger, nullable=False, default=0)
    updated_at_epoch = db.Column(db.BigInteger, nullable=False)

    def __repr__(self):
        return f"<LoginRateLimit scope={self.scope} attempts={self.failed_attempts}>"


class Service(db.Model):
    __tablename__ = "services"
    __table_args__ = (
        db.CheckConstraint(
            "length(trim(service_type)) > 0",
            name="ck_services_service_type_not_blank",
        ),
        db.Index("ix_services_type_active", "service_type", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    service_type = db.Column(db.String(100), nullable=False)  # e.g. "policy_evaluation"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    subscriptions = db.relationship(
        "Subscription",
        back_populates="service",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Service {self.name} ({self.service_type})>"


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "service_id",
            name="uq_subscriptions_user_service",
        ),
        db.CheckConstraint(
            "end_date IS NULL OR end_date > start_date",
            name="ck_subscriptions_valid_date_range",
        ),
        db.Index("ix_subscriptions_user_active", "user_id", "is_active"),
        db.Index("ix_subscriptions_service_active", "service_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    start_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    end_date = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="subscriptions")
    service = db.relationship("Service", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription user={self.user_id} service={self.service_id} active={self.is_active}>"


class Device(db.Model):
    """A collectible network device (currently FortiGate) registered by an admin.

    Credentials are stored encrypted (see secret_crypto.py) and are never
    rendered back into HTML. ``data_dir`` is the path (relative to the
    collector's working directory) where this device's snapshots live; each
    device gets its own isolated snapshot store so evaluation results never
    mix data between devices.
    """

    __tablename__ = "devices"
    __table_args__ = (
        db.CheckConstraint(
            "device_type IN ('fortigate')",
            name="ck_devices_device_type",
        ),
        db.CheckConstraint(
            "last_sync_status IS NULL OR last_sync_status IN ('success', 'failure')",
            name="ck_devices_last_sync_status",
        ),
        db.Index("ix_devices_type_active", "device_type", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    device_type = db.Column(db.String(50), nullable=False, default="fortigate")

    # Connection settings
    api_host = db.Column(db.String(255), nullable=False, default="")
    api_scheme = db.Column(db.String(10), nullable=False, default="https")
    vdom = db.Column(db.String(100), nullable=False, default="root")
    verify_ssl = db.Column(db.Boolean, nullable=False, default=False)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=30)
    skip_monitor_routes = db.Column(db.Boolean, nullable=False, default=False)
    keep_snapshots = db.Column(db.Integer, nullable=False, default=10)

    # Encrypted credentials. api_key is what the FortiGate collector uses
    # today; username/password are stored for device types added later.
    api_key_encrypted = db.Column(db.Text, nullable=True)
    auth_username_encrypted = db.Column(db.Text, nullable=True)
    auth_password_encrypted = db.Column(db.Text, nullable=True)

    data_dir = db.Column(db.String(500), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Populated by the sync service after each collection attempt.
    last_sync_at = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(db.String(20), nullable=True)  # "success" | "failure"
    last_sync_message = db.Column(db.Text, nullable=True)
    last_snapshot_id = db.Column(db.String(150), nullable=True)

    assignments = db.relationship(
        "DeviceAssignment",
        back_populates="device",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Device {self.name} ({self.device_type})>"


class DeviceAssignment(db.Model):
    """Grants a client user access to evaluate policies against one device."""

    __tablename__ = "device_assignments"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "device_id",
            name="uq_device_assignments_user_device",
        ),
        db.Index("ix_device_assignments_user_active", "user_id", "is_active"),
        db.Index("ix_device_assignments_device_active", "device_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    assigned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", back_populates="device_assignments")
    device = db.relationship("Device", back_populates="assignments")

    def __repr__(self):
        return (
            f"<DeviceAssignment user={self.user_id} device={self.device_id} "
            f"active={self.is_active}>"
        )


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

    posts = db.relationship(
        "BlogPost",
        back_populates="category",
        lazy="dynamic",
        passive_deletes=True,
    )

    @property
    def published_count(self):
        return self.posts.filter_by(status="published").count()

    def __repr__(self):
        return f"<BlogCategory {self.name}>"


class BlogPost(db.Model):
    __tablename__ = "blog_posts"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'published')",
            name="ck_blog_posts_status",
        ),
        db.Index("ix_blog_posts_status_published_at", "status", "published_at"),
        db.Index("ix_blog_posts_category_status", "category_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False, index=True)
    excerpt = db.Column(db.String(400), default="")
    content = db.Column(db.Text, nullable=False, default="")
    cover_image = db.Column(db.String(300), default="")  # path under /static, or empty
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | published
    category_id = db.Column(db.Integer, db.ForeignKey("blog_categories.id", ondelete="SET NULL"), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
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


def init_db(app):
    """Configure SQLAlchemy and verify database connectivity."""

    import time
    from sqlalchemy.exc import OperationalError

    from db_url import resolve_database_url

    app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    max_attempts = 10
    delay_seconds = 2

    for attempt in range(1, max_attempts + 1):
        try:
            with app.app_context():
                with db.engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            return

        except OperationalError as exc:
            if attempt == max_attempts:
                raise

            logger.warning(
                "Database not ready yet "
                "(attempt %d/%d): %s. Retrying in %ds...",
                attempt,
                max_attempts,
                exc,
                delay_seconds,
            )
            time.sleep(delay_seconds)


def seed_defaults():
    """Seed application defaults after migrations have completed."""
    _seed_defaults()

def _seed_defaults():
    """Seed defaults as one atomic transaction."""
    from security import hash_password
    from database_transactions import transaction

    with transaction("seed default application data"):
        bootstrap_user = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip().lower()
        bootstrap_password = read_secret("BOOTSTRAP_ADMIN_PASSWORD", default="") or ""
        admin = (
            User.query.filter_by(username=bootstrap_user).first()
            if bootstrap_user
            else None
        )

        if bootstrap_user and bootstrap_password and admin is None:
            if len(bootstrap_password) < 12:
                raise RuntimeError(
                    "BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters"
                )
            admin = User(
                username=bootstrap_user,
                password_hash=hash_password(bootstrap_password),
                salt="",
                role="admin",
            )
            db.session.add(admin)
            logger.info(
                "Bootstrap admin created",
                extra={
                    "event_type": "audit_user_created",
                    "target_username": bootstrap_user,
                },
            )

        default_services = [
            {
                "name": "Policy Evaluation",
                "description": "Evaluate FortiGate firewall policies for new access requests",
                "service_type": "policy_evaluation",
            },
            {
                "name": "Policy Risk Assessment",
                "description": "Score and rank firewall policies by security risk with remediation guidance",
                "service_type": "policy_risk_assessment",
            },
        ]
        for svc_data in default_services:
            if Service.query.filter_by(
                service_type=svc_data["service_type"]
            ).first() is None:
                db.session.add(Service(**svc_data))

        # Pre-multi-device installs collect into a single top-level "data"
        # directory with no associated Device row. Register it once so
        # existing snapshots keep working under the new device inventory
        # without moving any files. This only runs when no devices exist yet,
        # so it never overwrites an admin's own device inventory.
        if Device.query.count() == 0:
            legacy_device = Device(
                name="Default FortiGate",
                device_type="fortigate",
                data_dir="data",
                is_active=True,
            )
            db.session.add(legacy_device)
            logger.info(
                "Legacy default device registered",
                extra={
                    "event_type": "audit_device_created",
                    "device_name": legacy_device.name,
                },
            )

        if admin:
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

