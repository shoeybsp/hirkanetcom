from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .common import boolean_checkbox, choice, optional_int, password, service_type, text, username
from .errors import ValidationError


@dataclass(frozen=True)
class UserInput:
    username: str
    password: str
    role: str


def validate_user(data: Mapping, *, password_required: bool) -> UserInput:
    errors: dict[str, list[str]] = {}
    values = {}
    for field, fn in (
        ("username", lambda: username(data.get("username", ""))),
        ("password", lambda: password(data.get("password", ""), required=password_required)),
        ("role", lambda: choice(data, "role", {"admin", "client"}, default="client")),
    ):
        try:
            values[field] = fn()
        except ValidationError as exc:
            errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)
    return UserInput(**values)


@dataclass(frozen=True)
class ServiceInput:
    name: str
    description: str
    service_type: str
    is_active: bool


def validate_service(data: Mapping) -> ServiceInput:
    errors: dict[str, list[str]] = {}
    values = {}
    specs = (
        ("name", lambda: text(data, "name", required=True, max_length=200)),
        ("description", lambda: text(data, "description", max_length=5000)),
        ("service_type", lambda: service_type(data.get("service_type", ""))),
    )
    for field, fn in specs:
        try:
            values[field] = fn()
        except ValidationError as exc:
            errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)
    values["is_active"] = boolean_checkbox(data, "is_active")
    return ServiceInput(**values)


@dataclass(frozen=True)
class CategoryInput:
    name: str
    description: str


def validate_category(data: Mapping) -> CategoryInput:
    errors: dict[str, list[str]] = {}
    try:
        name = text(data, "name", required=True, max_length=120)
    except ValidationError as exc:
        errors.update(exc.errors); name = ""
    try:
        description = text(data, "description", max_length=5000)
    except ValidationError as exc:
        errors.update(exc.errors); description = ""
    if errors:
        raise ValidationError(errors)
    return CategoryInput(name, description)


@dataclass(frozen=True)
class BlogPostInput:
    title: str
    excerpt: str
    content: str
    status: str
    category_id: int | None
    remove_cover: bool


def validate_blog_post(data: Mapping, *, allowed_category_ids: set[int]) -> BlogPostInput:
    errors: dict[str, list[str]] = {}
    values = {}
    specs = (
        ("title", lambda: text(data, "title", required=True, max_length=200)),
        ("excerpt", lambda: text(data, "excerpt", max_length=400)),
        ("content", lambda: text(data, "content", required=True, max_length=200000)),
        ("status", lambda: choice(data, "status", {"draft", "published"}, default="draft")),
        ("category_id", lambda: optional_int(data, "category_id", allowed_ids=allowed_category_ids)),
    )
    for field, fn in specs:
        try:
            values[field] = fn()
        except ValidationError as exc:
            errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)
    values["remove_cover"] = boolean_checkbox(data, "remove_cover")
    return BlogPostInput(**values)


def validate_subscription_ids(raw_ids: Sequence[str], *, allowed_ids: set[int]) -> set[int]:
    selected: set[int] = set()
    errors: list[str] = []
    for raw in raw_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            errors.append(f"Invalid service identifier: {raw!r}.")
            continue
        if value not in allowed_ids:
            errors.append(f"Unknown service identifier: {value}.")
        else:
            selected.add(value)
    if errors:
        raise ValidationError({"services": errors})
    return selected


def validate_password_change(data: Mapping) -> tuple[str, str]:
    current = str(data.get("current_password", "") or "")
    new = str(data.get("new_password", "") or "")
    confirm = str(data.get("confirm_password", "") or "")
    errors: dict[str, list[str]] = {}
    if not current:
        errors.setdefault("current_password", []).append("Current password is required.")
    try:
        password(new, required=True)
    except ValidationError as exc:
        errors["new_password"] = exc.errors.get("password", [])
    if new != confirm:
        errors.setdefault("confirm_password", []).append("Passwords do not match.")
    if errors:
        raise ValidationError(errors)
    return current, new
