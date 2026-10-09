from __future__ import annotations

import ipaddress
import re
from typing import Iterable, Mapping

from urllib.parse import urlsplit

from .errors import ValidationError

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]+$")
_SERVICE_TYPE_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")


def text(data: Mapping, field: str, *, required: bool = False, max_length: int | None = None, lower: bool = False) -> str:
    value = str(data.get(field, "") or "").strip()
    if lower:
        value = value.lower()
    errors: dict[str, list[str]] = {}
    if required and not value:
        errors.setdefault(field, []).append("This field is required.")
    if max_length is not None and len(value) > max_length:
        errors.setdefault(field, []).append(f"Must be at most {max_length} characters.")
    if errors:
        raise ValidationError(errors)
    return value


def choice(data: Mapping, field: str, allowed: Iterable[str], *, default: str | None = None) -> str:
    allowed_set = set(allowed)
    value = str(data.get(field, default or "") or "").strip()
    if value not in allowed_set:
        raise ValidationError({field: [f"Must be one of: {', '.join(sorted(allowed_set))}."]})
    return value


def optional_int(data: Mapping, field: str, *, allowed_ids: set[int] | None = None) -> int | None:
    raw = str(data.get(field, "") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: ["Must be a valid integer identifier."]}) from None
    if value <= 0:
        raise ValidationError({field: ["Must be a positive identifier."]})
    if allowed_ids is not None and value not in allowed_ids:
        raise ValidationError({field: ["References an unknown record."]})
    return value


def boolean_checkbox(data: Mapping, field: str) -> bool:
    return str(data.get(field, "") or "").lower() in {"on", "true", "1", "yes"}


def bounded_int(
    data: Mapping,
    field: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str | None = None,
) -> int:
    """Validate a required integer setting field within an inclusive range."""
    raw = str(data.get(field, "") or "").strip()
    name = label or field
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: [f"{name} must be a whole number."]}) from None
    if value < minimum or value > maximum:
        raise ValidationError(
            {field: [f"{name} must be between {minimum} and {maximum}."]}
        )
    return value


def username(value: str) -> str:
    value = (value or "").strip().lower()
    errors: list[str] = []
    if not value:
        errors.append("Username is required.")
    elif len(value) > 100:
        errors.append("Username must be at most 100 characters.")
    elif not _USERNAME_RE.fullmatch(value):
        errors.append("Use only letters, numbers, dots, underscores, and hyphens.")
    if errors:
        raise ValidationError({"username": errors})
    return value


def password(value: str, *, required: bool = True) -> str:
    value = value or ""
    errors: list[str] = []
    if required and not value:
        errors.append("Password is required.")
    if value and len(value) < 12:
        errors.append("Password must be at least 12 characters.")
    if len(value) > 200:
        errors.append("Password must be at most 200 characters.")
    if errors:
        raise ValidationError({"password": errors})
    return value


def service_type(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        raise ValidationError({"service_type": ["Service type is required."]})
    if len(value) > 100:
        raise ValidationError({"service_type": ["Must be at most 100 characters."]})
    if not _SERVICE_TYPE_RE.fullmatch(value):
        raise ValidationError({"service_type": ["Use lowercase letters, numbers, underscores, or hyphens."]})
    return value


_HOST_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def host_address(value: str, *, field: str = "api_host") -> str:
    """Validate a device API host (hostname or IP, optional scheme and port).

    Rejects paths, query strings, fragments and embedded credentials so the
    stored value can only ever address a host:port, never an arbitrary URL.
    """
    value = (value or "").strip()
    errors: list[str] = []
    if not value:
        errors.append("API host is required.")
    elif len(value) > 255:
        errors.append("Must be at most 255 characters.")
    elif any(ch.isspace() for ch in value):
        errors.append("Must not contain whitespace.")
    else:
        candidate = value if "://" in value else f"https://{value}"
        try:
            parsed = urlsplit(candidate)
            port = parsed.port  # raises ValueError for a bad port
        except ValueError:
            parsed, port = None, None
            errors.append("Must be a valid host name or IP address with an optional port.")
        if parsed is not None:
            if parsed.scheme not in ("http", "https"):
                errors.append("Only http:// or https:// schemes are allowed.")
            elif parsed.username or parsed.password or "@" in parsed.netloc:
                errors.append("Must not contain credentials.")
            elif parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                errors.append("Enter only the host and optional port, without a path.")
            elif port is not None and not 1 <= port <= 65535:
                errors.append("Port must be between 1 and 65535.")
            else:
                hostname = parsed.hostname or ""
                try:
                    ipaddress.ip_address(hostname)
                    host_ok = True
                except ValueError:
                    host_ok = bool(hostname) and all(
                        _HOST_LABEL_RE.fullmatch(label) for label in hostname.rstrip(".").split(".")
                    )
                if not host_ok:
                    errors.append("Must be a valid host name or IP address.")
    if errors:
        raise ValidationError({field: errors})
    return value
