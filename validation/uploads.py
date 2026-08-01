from __future__ import annotations

import io
from pathlib import Path

from .errors import ValidationError

CSV_MAX_BYTES = 2 * 1024 * 1024
COVER_MAX_BYTES = 5 * 1024 * 1024
ALLOWED_COVER_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
_IMAGE_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}


def validate_csv_upload(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        raise ValidationError({"csv_file": ["Select a CSV file."]})
    if Path(file_storage.filename).suffix.lower() != ".csv":
        raise ValidationError({"csv_file": ["Only CSV files are accepted."]})
    raw = file_storage.stream.read(CSV_MAX_BYTES + 1)
    if len(raw) > CSV_MAX_BYTES:
        raise ValidationError({"csv_file": ["CSV file exceeds the 2 MB limit."]})
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError({"csv_file": ["CSV must be UTF-8 encoded."]}) from None


def validate_cover_image(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    ext = Path(file_storage.filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_COVER_EXTENSIONS:
        raise ValidationError({"cover_image": ["Use PNG, JPG, GIF, or WEBP."]})
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    valid = any(header.startswith(sig) for sig in _IMAGE_SIGNATURES[ext])
    if ext == "webp":
        valid = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if not valid:
        raise ValidationError({"cover_image": ["File contents do not match the image extension."]})
    return ext
