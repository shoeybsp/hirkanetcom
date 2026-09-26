from __future__ import annotations

from pathlib import Path

from .errors import ValidationError

CSV_MAX_BYTES = 2 * 1024 * 1024


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
