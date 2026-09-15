"""Reversible encryption for device credentials stored in the database.

Unlike user passwords (hashed one-way with scrypt in security.py), device
credentials such as API keys must be recoverable so the collector can use
them to authenticate to the device. They are encrypted at rest with Fernet
(AES-128-CBC + HMAC) using a key derived from DEVICE_CREDENTIAL_KEY, which is
read the same way as SECRET_KEY (see secret_utils.read_secret): either from
DEVICE_CREDENTIAL_KEY_FILE (Docker secret) or the DEVICE_CREDENTIAL_KEY
environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from secret_utils import read_secret

_ENV_NAME = "DEVICE_CREDENTIAL_KEY"
_DEV_ONLY_FALLBACK_MATERIAL = "development-only-device-credential-key"


class CredentialEncryptionError(RuntimeError):
    """Raised when a stored device credential cannot be encrypted or decrypted."""


def _fernet_key_from_material(material: str) -> bytes:
    """Derive a valid 32-byte urlsafe-base64-encoded Fernet key from secret material.

    DEVICE_CREDENTIAL_KEY is an operator-supplied string of any length, not
    necessarily a raw Fernet key, so it is hashed down to a fixed-size key.
    """
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _load_fernet() -> Fernet:
    env = os.getenv("APP_ENV", "development").lower()
    material = read_secret(_ENV_NAME, required=env == "production")
    if not material:
        # Only reached outside production, since read_secret raises above
        # when required=True and no value is configured.
        material = _DEV_ONLY_FALLBACK_MATERIAL
    return Fernet(_fernet_key_from_material(material))


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a credential value for storage. Falsy input stores as None."""
    if not plaintext:
        return None
    token = _load_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Decrypt a stored credential value. Falsy input returns None."""
    if not ciphertext:
        return None
    try:
        plaintext = _load_fernet().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        raise CredentialEncryptionError(
            "Stored device credential could not be decrypted. "
            "DEVICE_CREDENTIAL_KEY may be missing or has changed since this "
            "value was saved."
        ) from exc
    return plaintext.decode("utf-8")
