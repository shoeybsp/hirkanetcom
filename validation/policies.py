"""Input validation for policy search request parameters."""

from __future__ import annotations

from typing import Sequence

from validation.errors import ValidationError

VALID_ACTIONS = ("accept", "deny")
VALID_STATUSES = ("enable", "disable")
VALID_SORT_FIELDS = ("policyid", "name", "action")
VALID_SORT_ORDERS = ("asc", "desc")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class PolicySearchError(ValidationError):
    """Structured validation failure for policy search parameters."""
    pass


def validate_policy_search_params(
    *,
    action: str | None = None,
    status: str | None = None,
    limit: int | str | None = None,
    offset: int | str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    device_id: int | str | None = None,
) -> dict[str, int | str]:
    """Validate and normalize query parameters for policy search.

    Returns a dict of sanitized, ready-to-use parameters.

    Raises PolicySearchError if any parameter is invalid.
    """
    errors: dict[str, list[str]] = {}
    result: dict[str, int | str] = {}

    # action
    if action is not None:
        action_str = str(action).strip().lower()
        if action_str not in VALID_ACTIONS:
            errors["action"] = [f"Must be one of: {', '.join(VALID_ACTIONS)}"]
        else:
            result["action"] = action_str

    # status
    if status is not None:
        status_str = str(status).strip().lower()
        if status_str not in VALID_STATUSES:
            errors["status"] = [f"Must be one of: {', '.join(VALID_STATUSES)}"]
        else:
            result["status"] = status_str

    # device_id
    if device_id is not None:
        try:
            did = int(device_id)
            if did < 1:
                errors["device_id"] = ["Must be a positive integer"]
            else:
                result["device_id"] = did
        except (TypeError, ValueError):
            errors["device_id"] = ["Must be a valid integer"]

    # limit
    if limit is not None:
        try:
            lim = int(limit)
            if lim < 1 or lim > MAX_LIMIT:
                errors["limit"] = [f"Must be between 1 and {MAX_LIMIT}"]
            else:
                result["limit"] = lim
        except (TypeError, ValueError):
            errors["limit"] = ["Must be a valid integer"]

    # offset
    if offset is not None:
        try:
            off = int(offset)
            if off < 0:
                errors["offset"] = ["Must be non-negative"]
            else:
                result["offset"] = off
        except (TypeError, ValueError):
            errors["offset"] = ["Must be a valid integer"]

    # sort_by
    if sort_by is not None:
        sb = str(sort_by).strip().lower()
        if sb not in VALID_SORT_FIELDS:
            errors["sort_by"] = [f"Must be one of: {', '.join(VALID_SORT_FIELDS)}"]
        else:
            result["sort_by"] = sb

    # sort_order
    if sort_order is not None:
        so = str(sort_order).strip().lower()
        if so not in VALID_SORT_ORDERS:
            errors["sort_order"] = [f"Must be one of: {', '.join(VALID_SORT_ORDERS)}"]
        else:
            result["sort_order"] = so

    if errors:
        raise PolicySearchError(errors)

    return result
