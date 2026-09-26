"""Risk assessment service — search, filter, and paginate policy risk results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from engine.risk_assessor import (
    LEVEL_CRITICAL,
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    LEVEL_INFO,
    PolicyRiskAssessor,
    PolicyRiskResult,
)
from engine.snapshot_store import SnapshotError
from collectors.sync_service import resolve_device_data_root

logger = logging.getLogger(__name__)

VALID_RISK_LEVELS = (LEVEL_CRITICAL, LEVEL_HIGH, LEVEL_MEDIUM, LEVEL_LOW, LEVEL_INFO)
VALID_DIMENSIONS = ("address_scope", "logging", "config", "staleness")
VALID_SORT_FIELDS = ("risk_score", "policyid", "name")
VALID_SORT_ORDERS = ("asc", "desc")


class RiskAssessmentError(RuntimeError):
    """Raised when risk assessment encounters an unrecoverable error."""


@dataclass(frozen=True)
class RiskAssessmentResult:
    """Container for a page of risk assessment results with metadata."""

    data: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool
    filters_applied: dict[str, Any]
    summary: dict[str, Any]


class RiskAssessmentService:
    """Search and filter policy risk assessments.

    Loads the active snapshot for a given device, runs the risk assessor,
    and provides filtering across risk dimensions.  Stateless after
    construction; each instance loads a fresh snapshot.
    """

    def __init__(self, data_root: str):
        self.data_root = data_root
        self._assessor = PolicyRiskAssessor(data_root)
        self._results: list[PolicyRiskResult] = []
        self._snapshot_id: str = self._assessor.snapshot_id
        self._load()

    def _load(self) -> None:
        """Run the full assessment and cache results."""
        self._results = self._assessor.assess()

    def _to_dict(self, r: PolicyRiskResult) -> dict[str, Any]:
        """Convert a PolicyRiskResult to a JSON-serializable dict."""
        return {
            "policyid": r.policyid,
            "name": r.name,
            "action": r.action,
            "status": r.status,
            "risk_score": r.risk_score,
            "risk_level": r.risk_level,
            "factors": [
                {
                    "dimension": f.dimension,
                    "score": f.score,
                    "findings": f.findings,
                }
                for f in r.factors
            ],
            "remediation": r.remediation,
        }

    def get_assessment(
        self,
        *,
        risk_level: str | None = None,
        dimension: str | None = None,
        min_score: int | None = None,
        name: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "risk_score",
        sort_order: str = "desc",
    ) -> RiskAssessmentResult:
        """Apply filters and return paginated risk assessment results."""
        result = list(self._results)
        filters_applied: dict[str, Any] = {}

        # Filter by risk level
        if risk_level:
            level_lower = risk_level.lower()
            result = [r for r in result if r.risk_level == level_lower]
            filters_applied["risk_level"] = risk_level

        # Filter by worst dimension
        if dimension:
            dim_lower = dimension.lower()
            result = [
                r for r in result
                if any(f.dimension == dim_lower and f.score > 0 for f in r.factors)
            ]
            filters_applied["dimension"] = dimension

        # Filter by minimum score
        if min_score is not None:
            result = [r for r in result if r.risk_score >= min_score]
            filters_applied["min_score"] = min_score

        # Filter by name (case-insensitive substring)
        if name:
            search = name.lower()
            result = [r for r in result if search in r.name.lower()]
            filters_applied["name"] = name

        # Sort
        reverse = sort_order.lower() == "desc"
        if sort_by == "risk_score":
            result.sort(key=lambda r: r.risk_score, reverse=reverse)
        elif sort_by == "policyid":
            result.sort(key=lambda r: r.policyid or 0, reverse=reverse)
        elif sort_by == "name":
            result.sort(key=lambda r: r.name.lower(), reverse=reverse)
        else:
            result.sort(key=lambda r: r.risk_score, reverse=reverse)

        # Paginate
        total = len(result)
        page = result[offset: offset + limit]
        has_more = (offset + limit) < total

        return RiskAssessmentResult(
            data=[self._to_dict(r) for r in page],
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more,
            filters_applied=filters_applied,
            summary=self._assessor.get_summary(),
        )

    def get_policy_detail(self, policy_id: int) -> dict[str, Any] | None:
        """Return full risk details for a single policy."""
        result = self._assessor.assess_single(policy_id)
        if result is None:
            return None
        return self._to_dict(result)

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id
