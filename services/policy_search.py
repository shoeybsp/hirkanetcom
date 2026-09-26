"""Policy search and filtering service for collected FortiGate policies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from engine.snapshot_store import load_snapshot_dataset, SnapshotError
from collectors.sync_service import resolve_device_data_root

logger = logging.getLogger(__name__)


class PolicySearchError(RuntimeError):
    """Raised when policy search encounters an unrecoverable error."""


@dataclass(frozen=True)
class SearchResult:
    """Container for a page of search results with metadata."""

    data: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool
    filters_applied: dict[str, Any]


class PolicySearchService:
    """Search and filter collected FortiGate policies.

    Loads the active snapshot for a given device and provides filtering
    across all policy fields. The service is stateless after construction;
    each instance loads a fresh snapshot.
    """

    def __init__(self, data_root: str):
        self.data_root = data_root
        self._policies: list[dict[str, Any]] = []
        self._snapshot_id: str | None = None
        self._all_addresses: list[str] = []
        self._all_services: list[str] = []
        self._load_policies()

    def _load_policies(self) -> None:
        """Load and normalize policies from the active snapshot."""
        location, dataset, manifest = load_snapshot_dataset(self.data_root)
        self._snapshot_id = location.snapshot_id
        self._policies = self._normalize_policies(dataset.get("policies.json", []))
        self._build_catalogs()

    @staticmethod
    def _normalize_policies(raw_policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize raw policy data into a consistent searchable structure."""
        normalized = []
        for p in raw_policies:
            if not isinstance(p, dict):
                continue
            normalized.append({
                "policyid": p.get("policyid"),
                "name": p.get("name", ""),
                "action": p.get("action", ""),
                "status": p.get("status", "enable"),
                "srcaddr": _extract_names(p.get("srcaddr", [])),
                "dstaddr": _extract_names(p.get("dstaddr", [])),
                "service": _extract_names(p.get("service", [])),
                "srcintf": _extract_names(p.get("srcintf", [])),
                "dstintf": _extract_names(p.get("dstintf", [])),
                "logtraffic": p.get("logtraffic", ""),
                "schedule": p.get("schedule", ""),
                "utm_status": p.get("utm_status", ""),
            })
        return normalized

    def search(
        self,
        *,
        name: str | None = None,
        action: str | None = None,
        status: str | None = None,
        service: str | None = None,
        srcaddr: str | None = None,
        dstaddr: str | None = None,
        srcintf: str | None = None,
        dstintf: str | None = None,
        logtraffic: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "policyid",
        sort_order: str = "asc",
    ) -> SearchResult:
        """Apply filters and return paginated results.

        All string filters perform case-insensitive substring matching
        against the corresponding policy field. List fields (srcaddr,
        dstaddr, service, srcintf, dstintf) match if any element contains
        the filter string.
        """
        result = list(self._policies)

        # -- apply filters --
        filters_applied: dict[str, Any] = {}

        if name:
            search = name.lower()
            result = [p for p in result if search in p.get("name", "").lower()]
            filters_applied["name"] = name

        if action:
            action_lower = action.lower()
            result = [p for p in result if p.get("action", "").lower() == action_lower]
            filters_applied["action"] = action

        if status:
            status_lower = status.lower()
            result = [p for p in result if p.get("status", "").lower() == status_lower]
            filters_applied["status"] = status

        if service:
            search = service.lower()
            result = [p for p in result if _any_contains(p.get("service", []), search)]
            filters_applied["service"] = service

        if srcaddr:
            search = srcaddr.lower()
            result = [p for p in result if _any_contains(p.get("srcaddr", []), search)]
            filters_applied["srcaddr"] = srcaddr

        if dstaddr:
            search = dstaddr.lower()
            result = [p for p in result if _any_contains(p.get("dstaddr", []), search)]
            filters_applied["dstaddr"] = dstaddr

        if srcintf:
            search = srcintf.lower()
            result = [p for p in result if _any_contains(p.get("srcintf", []), search)]
            filters_applied["srcintf"] = srcintf

        if dstintf:
            search = dstintf.lower()
            result = [p for p in result if _any_contains(p.get("dstintf", []), search)]
            filters_applied["dstintf"] = dstintf

        if logtraffic:
            search = logtraffic.lower()
            result = [p for p in result if search in p.get("logtraffic", "").lower()]
            filters_applied["logtraffic"] = logtraffic

        # -- sort --
        reverse = sort_order.lower() == "desc"
        if sort_by in ("policyid", "name", "action"):
            result.sort(key=lambda p: p.get(sort_by, ""), reverse=reverse)
        else:
            result.sort(key=lambda p: p.get("policyid") or 0, reverse=reverse)

        # -- paginate --
        total = len(result)
        page = result[offset: offset + limit]
        has_more = (offset + limit) < total

        return SearchResult(
            data=page,
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more,
            filters_applied=filters_applied,
        )

    def _build_catalogs(self) -> None:
        """Build sorted unique lists of all addresses and services across policies."""
        addrs = set()
        svcs = set()
        for p in self._policies:
            for a in p.get("srcaddr", []):
                if a:
                    addrs.add(a)
            for a in p.get("dstaddr", []):
                if a:
                    addrs.add(a)
            for s in p.get("service", []):
                if s:
                    svcs.add(s)
        self._all_addresses = sorted(addrs, key=str.lower)
        self._all_services = sorted(svcs, key=str.lower)

    def get_filter_options(self) -> dict[str, list[str]]:
        """Return unique values for filter dropdowns."""
        return {
            "addresses": self._all_addresses,
            "services": self._all_services,
        }

    @property
    def snapshot_id(self) -> str | None:
        return self._snapshot_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_names(values: list[Any]) -> list[str]:
    """Extract names from a list of strings or dicts with a 'name' key."""
    names = []
    for v in values:
        if isinstance(v, dict) and v.get("name"):
            names.append(v["name"])
        elif isinstance(v, str) and v:
            names.append(v)
    return names


def _any_contains(items: list[str], substring: str) -> bool:
    """Return True if any item in the list contains the substring (case-insensitive)."""
    return any(substring in item.lower() for item in items)
