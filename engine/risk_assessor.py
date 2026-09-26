"""Policy risk assessment engine.

Scores collected FortiGate policies across four risk dimensions and
provides actionable remediation suggestions.  Does not reproduce
FortiGate packet processing and must not be used as an authoritative
allow/deny decision.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Any

from engine.snapshot_store import load_snapshot_dataset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_ADDRESS_SCOPE = 0.35
WEIGHT_LOGGING = 0.25
WEIGHT_CONFIG = 0.25
WEIGHT_STALENESS = 0.15

# ---------------------------------------------------------------------------
# Risk level thresholds
# ---------------------------------------------------------------------------
LEVEL_CRITICAL = "critical"
LEVEL_HIGH = "high"
LEVEL_MEDIUM = "medium"
LEVEL_LOW = "low"
LEVEL_INFO = "info"


def _risk_level(score: int) -> str:
    if score >= 80:
        return LEVEL_CRITICAL
    if score >= 60:
        return LEVEL_HIGH
    if score >= 40:
        return LEVEL_MEDIUM
    if score >= 20:
        return LEVEL_LOW
    return LEVEL_INFO


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskFactor:
    dimension: str  # "address_scope" | "logging" | "config" | "staleness"
    score: int  # 0-100 for this dimension
    findings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyRiskResult:
    policyid: int
    name: str
    risk_score: int  # 0-100 aggregate
    risk_level: str  # critical | high | medium | low | info
    action: str
    status: str
    factors: list[RiskFactor] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class PolicyRiskAssessor:
    """Score collected FortiGate policies by security risk.

    Loads the active snapshot for a given device and evaluates every
    enabled policy.  The assessor is stateless after construction; each
    instance loads a fresh snapshot.
    """

    def __init__(self, data_root: str):
        location, dataset, manifest = load_snapshot_dataset(data_root)
        self.snapshot_id = location.snapshot_id
        self.policies: list[dict[str, Any]] = dataset.get("policies.json", [])
        self.addresses: list[dict[str, Any]] = dataset.get("addresses.json", [])
        self.services: list[dict[str, Any]] = dataset.get("services.json", [])
        self.routes: list[dict[str, Any]] = dataset.get("routes.json", [])
        self.interfaces: list[dict[str, Any]] = dataset.get("interfaces.json", [])

        self._addr_map = self._build_addr_map()
        self._service_map = self._build_service_map()

    # -- data helpers -------------------------------------------------------

    def _build_addr_map(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for a in self.addresses:
            name = (a.get("name") or "").lower()
            if not name:
                continue
            if a.get("group"):
                out[name] = {"group": [
                    (x.get("name", x) if isinstance(x, dict) else x).lower()
                    for x in a.get("group", [])
                ]}
            elif "subnet" in a:
                out[name] = a["subnet"].replace(" ", "/")
            elif "iprange" in a:
                out[name] = a["iprange"]
            elif a.get("type") == "all":
                out[name] = "0.0.0.0/0"
        return out

    def _build_service_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for s in self.services:
            name = (s.get("name") or "").lower()
            if not name:
                continue
            out[name] = {
                "protocol": (s.get("protocol") or "").lower(),
                "tcp_portrange": s.get("tcp-portrange", ""),
                "udp_portrange": s.get("udp-portrange", ""),
                "group": [m.lower() for m in s.get("group", []) if m],
            }
        return out

    def _resolve_addr(self, name: str) -> str | None:
        """Resolve an address name to a CIDR or range string, or None."""
        val = self._addr_map.get(name.lower())
        if val is None:
            return None
        if isinstance(val, dict) and "group" in val:
            return None  # groups don't resolve to a single network
        return val

    @staticmethod
    def _is_broad_network(value: str | None) -> bool:
        """Return True for /0, /8, /16 or wider networks."""
        if not value:
            return False
        try:
            net = ipaddress.ip_network(value, strict=False)
            return net.prefixlen <= 16
        except ValueError:
            return False

    @staticmethod
    def _is_any_addr(name: str) -> bool:
        return name.lower() in ("all", "any", "0.0.0.0/0", "0.0.0.0 0.0.0.0")

    # -- normalization -------------------------------------------------------

    def _normalize_name_list(self, values: list[Any]) -> list[str]:
        out: list[str] = []
        for v in values:
            if isinstance(v, dict) and v.get("name"):
                out.append(v["name"].lower())
            elif isinstance(v, str) and v:
                out.append(v.lower())
        return out

    def _normalize_policies(self) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for p in self.policies:
            normalized.append({
                "policyid": p.get("policyid"),
                "name": p.get("name", ""),
                "action": p.get("action", "").lower(),
                "status": p.get("status", "enable").lower(),
                "srcaddr": self._normalize_name_list(p.get("srcaddr", [])),
                "dstaddr": self._normalize_name_list(p.get("dstaddr", [])),
                "service": self._normalize_name_list(p.get("service", [])),
                "srcintf": self._normalize_name_list(p.get("srcintf", [])),
                "dstintf": self._normalize_name_list(p.get("dstintf", [])),
                "logtraffic": (p.get("logtraffic") or "").lower(),
                "schedule": (p.get("schedule") or "").lower(),
                "utm_status": (p.get("utm_status") or "").lower(),
            })
        return normalized

    # -- scoring helpers -----------------------------------------------------

    def _score_address_scope(self, pol: dict[str, Any]) -> RiskFactor:
        """Score risk from broad or overly permissive address objects."""
        score = 0
        findings: list[str] = []
        remediation: list[str] = []

        srcaddr = pol["srcaddr"]
        dstaddr = pol["dstaddr"]

        # ANY in source
        src_any = [a for a in srcaddr if self._is_any_addr(a)]
        if src_any:
            score += 40
            findings.append("Source uses ANY (0.0.0.0/0) — accepts from all networks")
            remediation.append("Replace ANY source with the specific source address or address group")

        # ANY in destination
        dst_any = [a for a in dstaddr if self._is_any_addr(a)]
        if dst_any:
            score += 40
            findings.append("Destination uses ANY (0.0.0.0/0) — reaches all networks")
            remediation.append("Replace ANY destination with the specific destination address or address group")

        # Broad subnets
        broad_src = [a for a in srcaddr if not self._is_any_addr(a) and self._is_broad_network(self._resolve_addr(a))]
        broad_dst = [a for a in dstaddr if not self._is_any_addr(a) and self._is_broad_network(self._resolve_addr(a))]
        if broad_src:
            score += min(25, 12 * len(broad_src))
            findings.append(f"{len(broad_src)} source address(es) cover broad subnets (/16 or wider)")
            remediation.append("Narrow source addresses to more specific subnets")
        if broad_dst:
            score += min(25, 12 * len(broad_dst))
            findings.append(f"{len(broad_dst)} destination address(es) cover broad subnets (/16 or wider)")
            remediation.append("Narrow destination addresses to more specific subnets")

        # Too many address objects (sprawl)
        total_addrs = len(srcaddr) + len(dstaddr)
        if total_addrs > 20:
            score += 10
            findings.append(f"Policy references {total_addrs} address objects — may be overly broad or poorly organized")

        score = min(100, score)
        return RiskFactor(dimension="address_scope", score=score, findings=findings)

    def _score_logging(self, pol: dict[str, Any]) -> RiskFactor:
        """Score risk from missing or insufficient logging."""
        score = 0
        findings: list[str] = []
        remediation: list[str] = []

        logtraffic = pol["logtraffic"]
        utm = pol["utm_status"]

        if logtraffic in ("disable", "disableall", ""):
            score += 60
            findings.append("Traffic logging is disabled — policy hits are invisible")
            remediation.append("Enable logging (logtraffic: all or logtraffic: utm)")
        elif logtraffic == "utm":
            # UTM mode logs but only when UTM features trigger
            if "disable" in utm or not utm:
                score += 20
                findings.append("Logging set to UTM but UTM features appear disabled")

        # Check for denied traffic without logging
        if pol["action"] == "deny" and logtraffic in ("disable", "disableall", ""):
            score += 20
            findings.append("Deny rule has logging disabled — blocked traffic is not auditable")

        score = min(100, score)
        if score > 0 and not remediation:
            remediation.append("Enable traffic logging for audit visibility")

        return RiskFactor(dimension="logging", score=score, findings=findings)

    def _score_config(self, pol: dict[str, Any]) -> RiskFactor:
        """Score risk from weak or overly permissive configuration."""
        score = 0
        findings: list[str] = []
        remediation: list[str] = []

        # ALL interfaces
        if "all" in pol["srcintf"] or "any" in pol["srcintf"]:
            score += 25
            findings.append("Source interface set to ANY — applies from all network zones")
            remediation.append("Restrict source interface to the specific originating zone")
        if "all" in pol["dstintf"] or "any" in pol["dstintf"]:
            score += 25
            findings.append("Destination interface set to ANY — applies to all network zones")
            remediation.append("Restrict destination interface to the specific target zone")

        # ANY schedule (always-on rules that might be temporary)
        if pol["schedule"] in ("always", "all", ""):
            pass  # common and acceptable, no score
        elif pol["schedule"] not in ("", "always", "all"):
            # Has a schedule — might be intentional (good) or forgotten (bad)
            score += 5
            findings.append(f"Policy uses schedule '{pol['schedule']}' — verify it is still needed")

        # Disabled rules still in the base (staleness signal)
        if pol["status"] == "disable":
            score += 30
            findings.append("Policy is disabled but still present in configuration")
            remediation.append("Remove disabled rules that are no longer needed")

        # Too many services (sprawl)
        if len(pol["service"]) > 10:
            score += 10
            findings.append(f"Policy references {len(pol['service'])} service objects — may be too broad")

        score = min(100, score)
        return RiskFactor(dimension="config", score=score, findings=findings)

    def _score_staleness(self, pol: dict[str, Any]) -> RiskFactor:
        """Score risk from stale or unused policies."""
        score = 0
        findings: list[str] = []
        remediation: list[str] = []

        if pol["status"] == "disable":
            score += 70
            findings.append("Disabled policy may be stale — consider removal if no longer needed")
            remediation.append("Review and remove disabled policies that serve no purpose")

        # Rules with action "deny" and no logging are often "set and forget" leftovers
        if pol["action"] == "deny" and pol["logtraffic"] in ("disable", "disableall", ""):
            score += 20
            findings.append("Deny rule with no logging — possible leftover that was never reviewed")
            remediation.append("Enable logging on deny rules to track if they are still relevant")

        score = min(100, score)
        return RiskFactor(dimension="staleness", score=score, findings=findings)

    # -- public API ----------------------------------------------------------

    def assess(self) -> list[PolicyRiskResult]:
        """Assess all policies and return scored results sorted by risk (highest first)."""
        policies = self._normalize_policies()
        results: list[PolicyRiskResult] = []

        for pol in policies:
            factors = [
                self._score_address_scope(pol),
                self._score_logging(pol),
                self._score_config(pol),
                self._score_staleness(pol),
            ]

            # Weighted aggregate
            weighted = (
                factors[0].score * WEIGHT_ADDRESS_SCOPE
                + factors[1].score * WEIGHT_LOGGING
                + factors[2].score * WEIGHT_CONFIG
                + factors[3].score * WEIGHT_STALENESS
            )
            risk_score = int(round(min(100, max(0, weighted))))

            # Collect remediation from all dimensions
            remediation: list[str] = []
            for f in factors:
                for r in self._get_remediation(pol, f.dimension):
                    if r not in remediation:
                        remediation.append(r)

            results.append(PolicyRiskResult(
                policyid=pol["policyid"],
                name=pol["name"],
                risk_score=risk_score,
                risk_level=_risk_level(risk_score),
                action=pol["action"],
                status=pol["status"],
                factors=factors,
                remediation=remediation,
            ))

        results.sort(key=lambda r: r.risk_score, reverse=True)
        return results

    def _get_remediation(self, pol: dict[str, Any], dimension: str) -> list[str]:
        """Generate remediation items for a dimension based on the policy state."""
        remediation: list[str] = []

        if dimension == "address_scope":
            if any(self._is_any_addr(a) for a in pol["srcaddr"]):
                remediation.append("Replace ANY source with specific address objects")
            if any(self._is_any_addr(a) for a in pol["dstaddr"]):
                remediation.append("Replace ANY destination with specific address objects")
            broad_count = sum(
                1 for a in pol["srcaddr"] + pol["dstaddr"]
                if not self._is_any_addr(a) and self._is_broad_network(self._resolve_addr(a))
            )
            if broad_count:
                remediation.append("Narrow broad subnet definitions to /24 or more specific")

        elif dimension == "logging":
            if pol["logtraffic"] in ("disable", "disableall", ""):
                remediation.append("Enable traffic logging for audit visibility")
            if pol["action"] == "deny" and pol["logtraffic"] in ("disable", "disableall", ""):
                remediation.append("Enable logging on deny rules for security monitoring")

        elif dimension == "config":
            if "all" in pol["srcintf"] or "any" in pol["srcintf"]:
                remediation.append("Restrict source interface to originating zone")
            if "all" in pol["dstintf"] or "any" in pol["dstintf"]:
                remediation.append("Restrict destination interface to target zone")
            if pol["status"] == "disable":
                remediation.append("Remove disabled rules that are no longer needed")
            if len(pol["service"]) > 10:
                remediation.append("Split overly broad service lists into separate policies")

        elif dimension == "staleness":
            if pol["status"] == "disable":
                remediation.append("Review and remove disabled policies")
            if pol["action"] == "deny" and pol["logtraffic"] in ("disable", "disableall", ""):
                remediation.append("Audit unlogged deny rules for continued relevance")

        return remediation

    def assess_single(self, policy_id: int) -> PolicyRiskResult | None:
        """Return the risk assessment for a single policy by ID."""
        for result in self.assess():
            if result.policyid == policy_id:
                return result
        return None

    def get_summary(self) -> dict[str, Any]:
        """Return device-level risk summary statistics."""
        results = self.assess()
        if not results:
            return {
                "total_policies": 0,
                "avg_risk_score": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "info_count": 0,
            }

        return {
            "total_policies": len(results),
            "avg_risk_score": int(round(sum(r.risk_score for r in results) / len(results))),
            "critical_count": sum(1 for r in results if r.risk_level == LEVEL_CRITICAL),
            "high_count": sum(1 for r in results if r.risk_level == LEVEL_HIGH),
            "medium_count": sum(1 for r in results if r.risk_level == LEVEL_MEDIUM),
            "low_count": sum(1 for r in results if r.risk_level == LEVEL_LOW),
            "info_count": sum(1 for r in results if r.risk_level == LEVEL_INFO),
        }
