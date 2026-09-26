"""Input validation for risk assessment request parameters."""

from __future__ import annotations

from validation.errors import ValidationError

VALID_RISK_LEVELS = ("critical", "high", "medium", "low", "info")
VALID_DIMENSIONS = ("address_scope", "logging", "config", "staleness")
VALID_SORT_FIELDS = ("risk_score", "policyid", "name")
VALID_SORT_ORDERS = ("asc", "desc")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class RiskAssessmentError(ValidationError):
    """Structured validation failure for risk assessment parameters."""


def validate_risk_assessment_params(
    *,
    risk_level: str | None = None,
    dimension: str | None = None,
    min_score: int | str | None = None,
    limit: int | str | None = None,
    offset: int | str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> dict[str, int | str]:
    """Validate and normalize query parameters for risk assessment.

    Returns a dict of sanitized, ready-to-use parameters.

    Raises RiskAssessmentError if any parameter is invalid.
    """
    errors: dict[str, list[str]] = {}
    result: dict[str, int | str] = {}

    # risk_level
    if risk_level is not None:
        level_str = str(risk_level).strip().lower()
        if level_str not in VALID_RISK_LEVELS:
            errors["risk_level"] = [f"Must be one of: {', '.join(VALID_RISK_LEVELS)}"]
        else:
            result["risk_level"] = level_str

    # dimension
    if dimension is not None:
        dim_str = str(dimension).strip().lower()
        if dim_str not in VALID_DIMENSIONS:
            errors["dimension"] = [f"Must be one of: {', '.join(VALID_DIMENSIONS)}"]
        else:
            result["dimension"] = dim_str

    # min_score
    if min_score is not None:
        try:
            ms = int(min_score)
            if ms < 0 or ms > 100:
                errors["min_score"] = ["Must be between 0 and 100"]
            else:
                result["min_score"] = ms
        except (TypeError, ValueError):
            errors["min_score"] = ["Must be a valid integer"]

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
        raise RiskAssessmentError(errors)

    return result
