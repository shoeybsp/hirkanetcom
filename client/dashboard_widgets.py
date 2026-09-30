"""Dashboard widget layout for the client home page.

Every card a client can put on their home page is a *widget* with a stable
string key:

* ``service:<id>`` - a service the client is subscribed to
* ``policy_catalog`` - the always-available policy catalog

A client's layout is the ordered list of widget keys they chose to show,
stored as JSON in ``users.dashboard_layout``. ``NULL`` means the client has
never customised the page, so every available widget is shown (the layout
before this feature existed). ``[]`` means they deliberately emptied it.

Stored layouts are never trusted: keys are re-validated against what the
client can access on every read, so a cancelled subscription or a
hand-edited value can never surface a card they should not see.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

CATALOG_KEY = "policy_catalog"
SERVICE_KEY_PREFIX = "service:"

_ICON_EVALUATION = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
_ICON_RISK = (
    '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86'
    'a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>'
    '<line x1="12" y1="17" x2="12.01" y2="17"/>'
)
_ICON_DOS = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>'
_ICON_UNKNOWN = (
    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
    '<line x1="12" y1="16" x2="12.01" y2="16"/>'
)
_ICON_CATALOG = (
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>'
    '<line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>'
)

# service_type -> how its widget looks and where it links
SERVICE_WIDGETS: dict[str, dict[str, str]] = {
    "policy_evaluation": {
        "endpoint": "client.policy_evaluation",
        "cta": "Open Service",
        "description": "Evaluate FortiGate firewall policies for new access requests.",
        "icon": _ICON_EVALUATION,
    },
    "policy_risk_assessment": {
        "endpoint": "client.risk_assessment",
        "cta": "Open Assessment",
        "description": "Score and rank firewall policies by security risk with remediation guidance.",
        "icon": _ICON_RISK,
    },
    "dos_policy": {
        "endpoint": "client.dos_policies",
        "cta": "Open DoS Policies",
        "description": "View and audit FortiGate DoS policies in real-time.",
        "icon": _ICON_DOS,
    },
}

MAX_STORED_LAYOUT_BYTES = 4096


def service_widget_key(service_id: int) -> str:
    return f"{SERVICE_KEY_PREFIX}{service_id}"


def build_available_widgets(services: Iterable[Any]) -> list[dict[str, Any]]:
    """Return every widget the client may show, in the default order."""
    widgets: list[dict[str, Any]] = []
    for svc in services:
        known = SERVICE_WIDGETS.get(svc.service_type)
        if known:
            widgets.append({
                "key": service_widget_key(svc.id),
                "title": svc.name,
                "description": svc.description or known["description"],
                "endpoint": known["endpoint"],
                "cta": known["cta"],
                "icon": known["icon"],
            })
        else:
            # Service types without a page yet render as a "Coming Soon" card.
            widgets.append({
                "key": service_widget_key(svc.id),
                "title": svc.name,
                "description": svc.description or "No description available.",
                "endpoint": None,
                "cta": "Coming Soon",
                "icon": _ICON_UNKNOWN,
            })
    widgets.append({
        "key": CATALOG_KEY,
        "title": "Policy Catalog",
        "description": "Browse, search, and filter collected firewall policies across your assigned devices.",
        "endpoint": "client.policy_catalog",
        "cta": "Open Catalog",
        "icon": _ICON_CATALOG,
    })
    return widgets


def parse_layout(raw: str | None) -> list[str] | None:
    """Decode a stored layout. ``None`` means "never customised"."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None  # corrupt value: fall back to the default layout
    if not isinstance(value, list):
        return None
    return [key for key in value if isinstance(key, str)]


def sanitize_layout(keys: Any, available: list[dict[str, Any]]) -> list[str]:
    """Keep only known, de-duplicated keys, preserving the given order."""
    allowed = {widget["key"] for widget in available}
    if not isinstance(keys, list):
        raise ValueError("layout must be a list of widget keys")
    cleaned: list[str] = []
    for key in keys:
        if isinstance(key, str) and key in allowed and key not in cleaned:
            cleaned.append(key)
    return cleaned


def resolve_layout(
    available: list[dict[str, Any]], raw: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split available widgets into (shown in saved order, hidden)."""
    stored = parse_layout(raw)
    if stored is None:
        return list(available), []
    by_key = {widget["key"]: widget for widget in available}
    ordered_keys = sanitize_layout(stored, available)
    shown = [by_key[key] for key in ordered_keys]
    hidden = [widget for widget in available if widget["key"] not in ordered_keys]
    return shown, hidden


def serialize_layout(keys: list[str]) -> str:
    return json.dumps(keys, separators=(",", ":"))
