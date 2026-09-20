"""API key generation and hashing for the FastAPI pilot service.

Deliberately separate from security.py's password hashing: API keys are
already high-entropy random tokens rather than user-chosen secrets, so the
slow, salted scrypt hashing used for passwords would only add per-request
CPU cost here without adding real security. A plain SHA-256 hash of the
key is sufficient and lets lookup happen as a simple indexed equality
query (ApiKey.key_hash == sha256(presented_key)).
"""

from __future__ import annotations

import hashlib
import secrets

_PREFIX = "hnk_"
_TOKEN_BYTES = 32  # 256 bits of entropy


def generate_api_key() -> str:
    """Generate a new, high-entropy raw API key.

    The "hnk_" prefix is purely cosmetic - it makes Hirkanet keys
    recognizable at a glance in logs, config files, or secret scanners,
    the same way many providers (Stripe, GitHub, etc.) prefix their keys.
    It carries no security meaning by itself.
    """
    return f"{_PREFIX}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_api_key(raw_key: str) -> str:
    """Return the hex-encoded SHA-256 hash of a raw API key for storage/lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
