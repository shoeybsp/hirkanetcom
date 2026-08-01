from __future__ import annotations

import re
from typing import Iterable, Mapping

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
