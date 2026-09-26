from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .common import (
    boolean_checkbox,
    bounded_int,
    choice,
    host_address,
    password,
    service_type,
    text,
    username,
)
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


_DEVICE_TYPES = {"fortigate"}
_API_SCHEMES = {"http", "https"}


@dataclass(frozen=True)
class DeviceInput:
    name: str
    device_type: str
    api_host: str
    api_scheme: str
    vdom: str
    verify_ssl: bool
    timeout_seconds: int
    skip_monitor_routes: bool
    keep_snapshots: int
    is_active: bool
    # Write-only credential fields. An empty string means "leave the
    # currently stored value unchanged" when editing an existing device.
    api_key: str
    auth_username: str
    auth_password: str


def validate_device(data: Mapping) -> DeviceInput:
    errors: dict[str, list[str]] = {}
    values = {}
    specs = (
        ("name", lambda: text(data, "name", required=True, max_length=200)),
        ("device_type", lambda: choice(data, "device_type", _DEVICE_TYPES, default="fortigate")),
        ("api_host", lambda: host_address(data.get("api_host", ""))),
        ("api_scheme", lambda: choice(data, "api_scheme", _API_SCHEMES, default="https")),
        ("vdom", lambda: text(data, "vdom", max_length=100)),
        (
            "timeout_seconds",
            lambda: bounded_int(
                data, "timeout_seconds", default=30, minimum=5, maximum=300, label="Timeout"
            ),
        ),
        (
            "keep_snapshots",
            lambda: bounded_int(
                data, "keep_snapshots", default=10, minimum=1, maximum=100, label="Snapshots to keep"
            ),
        ),
        ("api_key", lambda: text(data, "api_key", max_length=500)),
        ("auth_username", lambda: text(data, "auth_username", max_length=200)),
        ("auth_password", lambda: text(data, "auth_password", max_length=500)),
    )
    for field, fn in specs:
        try:
            values[field] = fn()
        except ValidationError as exc:
            errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)
    if not values["vdom"]:
        values["vdom"] = "root"
    values["verify_ssl"] = boolean_checkbox(data, "verify_ssl")
    values["skip_monitor_routes"] = boolean_checkbox(data, "skip_monitor_routes")
    values["is_active"] = boolean_checkbox(data, "is_active")
    return DeviceInput(**values)


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


def validate_device_assignment_user_ids(raw_ids: Sequence[str], *, allowed_ids: set[int]) -> set[int]:
    selected: set[int] = set()
    errors: list[str] = []
    for raw in raw_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            errors.append(f"Invalid client identifier: {raw!r}.")
            continue
        if value not in allowed_ids:
            errors.append(f"Unknown client identifier: {value}.")
        else:
            selected.add(value)
    if errors:
        raise ValidationError({"users": errors})
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
