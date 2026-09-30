"""Input validation for DoS policy listing parameters."""

from __future__ import annotations


from validation.errors import ValidationError

VALID_STATUS_VALUES = ("enable", "disable")
VALID_SORT_FIELDS = ("id", "name", "status")
VALID_SORT_ORDERS = ("asc", "desc")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class DosPolicyValidationError(ValidationError):
    """Structured validation failure for DoS policy parameters."""


def validate_dos_policy_list_params(
    *,
    limit: int | str | None = None,
    offset: int | str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    status: str | None = None,
    name: str | None = None,
) -> dict[str, int | str]:
    """Validate and normalize query parameters for DoS policy listing.

    Returns a dict of sanitized, ready-to-use parameters.

    Raises DosPolicyValidationError if any parameter is invalid.
    """
    errors: dict[str, list[str]] = {}
    result: dict[str, int | str] = {}

    if limit is not None:
        try:
            lim = int(limit)
            if lim < 1 or lim > MAX_LIMIT:
                errors["limit"] = [f"Must be between 1 and {MAX_LIMIT}"]
            else:
                result["limit"] = lim
        except (TypeError, ValueError):
            errors["limit"] = ["Must be a valid integer"]

    if offset is not None:
        try:
            off = int(offset)
            if off < 0:
                errors["offset"] = ["Must be non-negative"]
            else:
                result["offset"] = off
        except (TypeError, ValueError):
            errors["offset"] = ["Must be a valid integer"]

    if sort_by is not None:
        sb = str(sort_by).strip().lower()
        if sb not in VALID_SORT_FIELDS:
            errors["sort_by"] = [f"Must be one of: {', '.join(VALID_SORT_FIELDS)}"]
        else:
            result["sort_by"] = sb

    if sort_order is not None:
        so = str(sort_order).strip().lower()
        if so not in VALID_SORT_ORDERS:
            errors["sort_order"] = [f"Must be one of: {', '.join(VALID_SORT_ORDERS)}"]
        else:
            result["sort_order"] = so

    if status is not None:
        s = str(status).strip().lower()
        if s not in VALID_STATUS_VALUES:
            errors["status"] = [f"Must be one of: {', '.join(VALID_STATUS_VALUES)}"]
        else:
            result["status"] = s

    if name is not None:
        n = str(name).strip()
        if not n:
            errors["name"] = ["Name cannot be empty"]
        else:
            result["name"] = n

    if errors:
        raise DosPolicyValidationError(errors)
    return result
