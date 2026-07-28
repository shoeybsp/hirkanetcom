"""Password hashing with transparent migration from the legacy SHA-256 format."""
import hashlib
import hmac
from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")

def verify_password(user, password: str) -> bool:
    stored = user.password_hash or ""
    if stored.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored, password)
    salt = getattr(user, "salt", "") or ""
    legacy = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    if hmac.compare_digest(legacy, stored):
        user.password_hash = hash_password(password)
        user.salt = ""
        return True
    return False
