import os
from werkzeug.security import generate_password_hash, check_password_hash
import json
import threading


class User:
    """Represents an authenticated user."""

    def __init__(self, user_id: str, username: str, role: str = "viewer"):
        self.id = user_id
        self.username = username
        self.role = role  # "admin" or "viewer"

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return self.id

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class UserStore:
    """
    Thread-safe file-backed user store.
    Passwords are stored using Werkzeug scrypt hashes.
    """

    def __init__(self, path: str | None = None):
        self._lock = threading.Lock()
        self._path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "users.json",
        )
        self._users: dict[str, dict] = {}  # username -> {password_hash, salt, role, id}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        return generate_password_hash(password, method="scrypt"), ""

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            self._users = {}
            return
        try:
            with open(self._path, "r") as f:
                self._users = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._users = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._users, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
    ) -> User:
        """Create a new user. Raises ValueError if the username already exists."""
        username = username.strip().lower()
        if not username:
            raise ValueError("Username cannot be empty.")
        if not password or len(password) < 12:
            raise ValueError("Password must be at least 4 characters.")
        if role not in ("admin", "viewer"):
            raise ValueError("Role must be 'admin' or 'viewer'.")

        with self._lock:
            if username in self._users:
                raise ValueError(f"User '{username}' already exists.")

            pw_hash, salt = self._hash_password(password)
            user_id = os.urandom(16).hex()
            self._users[username] = {
                "id": user_id,
                "password_hash": pw_hash,
                "salt": salt,
                "role": role,
            }
            self._save()

        return User(user_id, username, role)

    def authenticate(self, username: str, password: str) -> User | None:
        """Return a User on success, or None on failure."""
        username = username.strip().lower()
        with self._lock:
            record = self._users.get(username)
            if record is None:
                return None
            if not check_password_hash(record["password_hash"], password):
                return None
            return User(record["id"], username, record["role"])

    def get_by_id(self, user_id: str) -> User | None:
        with self._lock:
            for username, record in self._users.items():
                if record["id"] == user_id:
                    return User(record["id"], username, record["role"])
        return None

    def get_by_username(self, username: str) -> User | None:
        username = username.strip().lower()
        with self._lock:
            record = self._users.get(username)
            if record is None:
                return None
            return User(record["id"], username, record["role"])

    def list_users(self) -> list[dict]:
        with self._lock:
            return [
                {"id": r["id"], "username": u, "role": r["role"]}
                for u, r in self._users.items()
            ]

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        username = username.strip().lower()
        with self._lock:
            record = self._users.get(username)
            if record is None:
                return False
            if not check_password_hash(record["password_hash"], old_password):
                return False
            new_hash, new_salt = self._hash_password(new_password)
            record["password_hash"] = new_hash
            record["salt"] = new_salt
            self._save()
        return True

    def remove_user(self, username: str) -> bool:
        username = username.strip().lower()
        with self._lock:
            if username not in self._users:
                return False
            del self._users[username]
            self._save()
        return True

    def ensure_admin(self, username: str, password: str) -> User:
        """Idempotent – create the admin user if it doesn't exist yet."""
        existing = self.get_by_username(username)
        if existing is not None:
            return existing
        return self.add_user(username, password, role="admin")