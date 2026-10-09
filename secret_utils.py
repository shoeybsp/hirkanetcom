"""Small helpers for loading secrets from Docker secret files."""

from __future__ import annotations

import os
from pathlib import Path


def read_secret(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """Read NAME_FILE first, then NAME for local-development compatibility."""
    file_path = os.getenv(f"{name}_FILE")
    value: str | None = None
    if file_path:
        try:
            value = Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Unable to read secret file for {name}: {file_path}") from exc
    elif name in os.environ:
        value = os.environ[name].strip()
    else:
        value = default

    if required and not value:
        source = f"{name}_FILE or {name}"
        raise RuntimeError(f"{source} is required")
    return value


_PLACEHOLDER_MARKERS = ("change-me", "changeme", "development-only", "replace-me", "example")


def is_placeholder_secret(value: str | None) -> bool:
    """True for the template/dev values shipped in env.example or the code."""
    lowered = (value or "").strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
