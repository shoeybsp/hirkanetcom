"""DoS policy audit engine.

Evaluates FortiGate DoS policies against security best practices and
provides actionable findings with remediation guidance.  Does not
reproduce FortiGate packet processing and must not be used as an
authoritative allow/deny decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_ANOMALY_COVERAGE = 0.30
WEIGHT_THRESHOLD_CONFIG = 0.25
WEIGHT_LOGGING = 0.20
WEIGHT_POLICY_SCOPE = 0.15
WEIGHT_ACTION = 0.10

# ---------------------------------------------------------------------------
# Risk level thresholds (same as PolicyRiskAssessor)
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
# Critical anomalies that should always be enabled
# ---------------------------------------------------------------------------
CRITICAL_ANOMALIES = frozenset({
    "tcp_syn_flood",
    "icmp_flood",
    "udp_flood",
    "tcp_udp_flood",
    "ip_spoofing",
    "land_attack",
})

RECOMMENDED_ANOMALIES = frozenset({
    "tcp_syn_flood",
    "icmp_flood",
    "udp_flood",
    "tcp_udp_flood",
    "tcp_syn_proxy",
    "tcp_port_scan",
    "tcp_udp_other",
    "icmp_land",
    "udp_land",
    "ip_spoofing",
    "land_attack",
    "ip_martian_source",
    "ip_bad_options",
    "ip_unknown_protocol",
    "tcp_crlf",
    "tcp_no_flag",
    "tcp_syn_fin",
    "tcp_syn_rst",
    "tcp_fin_no_ack",
    "tcp_xmas",
    "tcp_null",
    "tcp_fin_only",
    "udp_broadcast",
})

# Default thresholds considered too permissive (low) or too restrictive (high)
# for key anomaly types.  These are rough guidelines; tuning depends on
# the specific network environment.
DEFAULT_THRESHOLDS: dict[str, int] = {
    "tcp_syn_flood": 1000,
    "icmp_flood": 500,
    "udp_flood": 500,
    "tcp_udp_flood": 500,
}

THRESHOLD_LOW_MULTIPLIER = 0.1   # < 10% of default = likely too restrictive
THRESHOLD_HIGH_MULTIPLIER = 10.0  # > 10x default = likely too permissive


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DosAnomalyFinding:
    """A single anomaly-level audit finding."""

    anomaly_name: str
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    message: str
    remediation: str


@dataclass(frozen=True)
class DimensionScore:
    """Score and findings for one audit dimension."""

    dimension: str  # "anomaly_coverage" | "threshold_config" | "logging" | "policy_scope" | "action"
    score: int  # 0-100 (100 = no issues)
    findings: list[str] = field(default_factory=list)
    anomaly_findings: list[DosAnomalyFinding] = field(default_factory=list)


@dataclass(frozen=True)
class DosPolicyAuditResult:
    """Complete audit result for a single DoS policy."""

    policy_id: int | None
    name: str
    status: str
    audit_score: int  # 0-100 aggregate (100 = best)
    risk_level: str  # critical | high | medium | low | info
    dimensions: list[DimensionScore] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class DosPolicyAuditor:
    """Score FortiGate DoS policies by security posture.

    Loads a list of DoS policy dicts (from the FortiGate API) and
    evaluates every policy.  The auditor is stateless after
    construction; each instance works on the policies provided to it.
    """

    def __init__(self, policies: list[dict[str, Any]] | None = None):
        self._policies: list[dict[str, Any]] = policies or []
        self._results: list[DosPolicyAuditResult] = []

    def set_policies(self, policies: list[dict[str, Any]]) -> None:
        """Set the policies to audit and clear cached results."""
        self._policies = policies
        self._results = []

    def audit(self) -> list[DosPolicyAuditResult]:
        """Audit all loaded policies and return results."""
        self._results = [self._audit_single(p) for p in self._policies]
        return list(self._results)

    def audit_single(self, policy_id: int) -> DosPolicyAuditResult | None:
        """Audit a single policy by its ID."""
        for policy in self._policies:
            try:
                if int(policy.get("id")) == int(policy_id):
                    return self._audit_single(policy)
            except (TypeError, ValueError):
                continue  # missing or non-numeric id can't match
        return None

    def get_summary(self) -> dict[str, Any]:
        """Return aggregate summary statistics."""
        if not self._results:
            return {
                "total_policies": 0,
                "avg_score": 0,
                "risk_counts": {LEVEL_CRITICAL: 0, LEVEL_HIGH: 0, LEVEL_MEDIUM: 0, LEVEL_LOW: 0, LEVEL_INFO: 0},
                "enabled_count": 0,
                "disabled_count": 0,
            }

        risk_counts = {LEVEL_CRITICAL: 0, LEVEL_HIGH: 0, LEVEL_MEDIUM: 0, LEVEL_LOW: 0, LEVEL_INFO: 0}
        for r in self._results:
            risk_counts[r.risk_level] = risk_counts.get(r.risk_level, 0) + 1

        enabled = sum(1 for p in self._policies if p.get("status") == "enable")
        return {
            "total_policies": len(self._results),
            "avg_score": round(sum(r.audit_score for r in self._results) / len(self._results)),
            "risk_counts": risk_counts,
            "enabled_count": enabled,
            "disabled_count": len(self._policies) - enabled,
        }

    # -- Per-policy audit -----------------------------------------------------

    def _audit_single(self, policy: dict[str, Any]) -> DosPolicyAuditResult:
        """Produce a complete audit result for one policy."""
        anomalies = policy.get("anomaly", [])
        if isinstance(anomalies, dict):
            anomalies = list(anomalies.values()) if anomalies else []

        dim_coverage = self._score_anomaly_coverage(anomalies)
        dim_threshold = self._score_threshold_config(anomalies)
        dim_logging = self._score_logging(policy, anomalies)
        dim_scope = self._score_policy_scope(policy)
        dim_action = self._score_action(policy, anomalies)

        # Threshold, logging and action are scored per enabled anomaly, so a
        # policy with no enabled anomaly checks would otherwise earn full or
        # near-full marks there for having nothing to get wrong. Nothing is
        # protecting the network, so those dimensions score zero.
        if not any(
            isinstance(a, dict) and a.get("status") == "enable" for a in anomalies
        ):
            msg = "No anomaly checks are enabled — no thresholds, actions or logging are in effect"
            dim_threshold = DimensionScore("threshold_config", 0, [msg])
            dim_logging = DimensionScore("logging", 0, [msg])
            dim_action = DimensionScore("action", 0, [msg])

        dimensions = [dim_coverage, dim_threshold, dim_logging, dim_scope, dim_action]

        # Weighted aggregate
        raw = (
            dim_coverage.score * WEIGHT_ANOMALY_COVERAGE
            + dim_threshold.score * WEIGHT_THRESHOLD_CONFIG
            + dim_logging.score * WEIGHT_LOGGING
            + dim_scope.score * WEIGHT_POLICY_SCOPE
            + dim_action.score * WEIGHT_ACTION
        )
        audit_score = max(0, min(100, round(raw)))
        # audit_score is a posture score (higher = better), while
        # _risk_level() takes a risk score (higher = worse), so the
        # value is inverted before banding. This mirrors nothing in
        # risk_assessor, whose risk_score already increases with risk.
        risk_level = _risk_level(100 - audit_score)

        # Collect all remediation items
        remediation: list[str] = []
        for dim in dimensions:
            for finding in dim.anomaly_findings:
                if finding.remediation and finding.remediation not in remediation:
                    remediation.append(finding.remediation)
            for msg in dim.findings:
                if msg not in remediation:
                    remediation.append(msg)

        try:
            policy_id = int(policy.get("id"))
        except (TypeError, ValueError):
            policy_id = None
        return DosPolicyAuditResult(
            policy_id=policy_id,
            name=policy.get("name", "Unnamed"),
            status=policy.get("status", "unknown"),
            audit_score=audit_score,
            risk_level=risk_level,
            dimensions=dimensions,
            remediation=remediation,
        )

    # -- Dimension scorers ----------------------------------------------------

    def _score_anomaly_coverage(self, anomalies: list[dict]) -> DimensionScore:
        """Score based on which anomalies are enabled (0-100)."""
        enabled_names = {
            a.get("name", "") for a in anomalies
            if a.get("status") == "enable"
        }

        findings: list[str] = []
        anomaly_findings: list[DosAnomalyFinding] = []

        # Check critical anomalies
        missing_critical = CRITICAL_ANOMALIES - enabled_names
        for name in sorted(missing_critical):
            anomaly_findings.append(DosAnomalyFinding(
                anomaly_name=name,
                severity="critical",
                message=f"Critical anomaly '{name}' is not enabled",
                remediation=f"Enable the '{name}' anomaly to protect against this attack vector",
            ))

        # Check recommended anomalies
        missing_recommended = RECOMMENDED_ANOMALIES - enabled_names - CRITICAL_ANOMALIES
        for name in sorted(missing_recommended):
            anomaly_findings.append(DosAnomalyFinding(
                anomaly_name=name,
                severity="medium",
                message=f"Recommended anomaly '{name}' is not enabled",
                remediation=f"Consider enabling the '{name}' anomaly for broader protection",
            ))

        # Calculate score: each missing critical costs more than missing recommended
        total_critical = len(CRITICAL_ANOMALIES)
        total_recommended = len(RECOMMENDED_ANOMALIES - CRITICAL_ANOMALIES)
        missing_c = len(missing_critical)
        missing_r = len(missing_recommended)

        if total_critical > 0:
            critical_score = max(0, 100 - (missing_c / total_critical) * 70)
        else:
            critical_score = 100

        if total_recommended > 0:
            recommended_score = max(0, 100 - (missing_r / total_recommended) * 30)
        else:
            recommended_score = 100

        score = round(critical_score * 0.7 + recommended_score * 0.3)

        if not anomalies:
            findings.append("No anomaly configurations found in this policy")

        return DimensionScore(
            dimension="anomaly_coverage",
            score=score,
            findings=findings,
            anomaly_findings=anomaly_findings,
        )

    def _score_threshold_config(self, anomalies: list[dict]) -> DimensionScore:
        """Score based on threshold configuration (0-100)."""
        findings: list[str] = []
        anomaly_findings: list[DosAnomalyFinding] = []
        scored = 0
        total_penalty = 0

        for anomaly in anomalies:
            name = anomaly.get("name", "")
            status = anomaly.get("status", "disable")
            threshold = anomaly.get("threshold")
            if status != "enable" or name not in DEFAULT_THRESHOLDS or threshold is None:
                continue

            try:
                threshold_val = int(threshold)
            except (TypeError, ValueError):
                continue

            default = DEFAULT_THRESHOLDS[name]
            scored += 1

            if threshold_val < default * THRESHOLD_LOW_MULTIPLIER:
                total_penalty += 20
                anomaly_findings.append(DosAnomalyFinding(
                    anomaly_name=name,
                    severity="medium",
                    message=f"Threshold for '{name}' is very low ({threshold_val}), may cause false positives",
                    remediation=f"Increase the '{name}' threshold to reduce false positives (suggested: {default})",
                ))
            elif threshold_val > default * THRESHOLD_HIGH_MULTIPLIER:
                total_penalty += 15
                anomaly_findings.append(DosAnomalyFinding(
                    anomaly_name=name,
                    severity="high",
                    message=f"Threshold for '{name}' is very high ({threshold_val}), may miss real attacks",
                    remediation=f"Lower the '{name}' threshold for better protection (suggested: {default})",
                ))

        if scored == 0:
            score = 80  # Neutral if no thresholds are configurable
            findings.append("No threshold-based anomalies are active; consider enabling flood detection")
        else:
            score = max(0, 100 - total_penalty)

        return DimensionScore(
            dimension="threshold_config",
            score=score,
            findings=findings,
            anomaly_findings=anomaly_findings,
        )

    def _score_logging(self, policy: dict, anomalies: list[dict]) -> DimensionScore:
        """Score based on logging configuration (0-100).

        FortiGate DoS policies have logging per-anomaly only (no policy-level
        ``log-packet`` field).  The auditor checks that each active anomaly
        that blocks or quarantines also has ``log`` enabled.
        """
        findings: list[str] = []
        anomaly_findings: list[DosAnomalyFinding] = []
        score = 100

        # Check per-anomaly logging
        anomalies_with_logging = sum(
            1 for a in anomalies
            if a.get("status") == "enable" and a.get("log") == "enable"
        )
        enabled_anomalies = sum(
            1 for a in anomalies if a.get("status") == "enable"
        )

        if enabled_anomalies == 0:
            score = 60
            findings.append("No anomaly configurations found — enable anomalies with logging for visibility")
        elif enabled_anomalies > 0:
            logging_ratio = anomalies_with_logging / enabled_anomalies
            if logging_ratio < 0.5:
                score -= 30
                findings.append(
                    f"Only {anomalies_with_logging}/{enabled_anomalies} active anomalies have logging enabled"
                )
            elif logging_ratio < 1.0:
                score -= 15
                findings.append(
                    f"{enabled_anomalies - anomalies_with_logging} active anomalies have logging disabled"
                )

        # Check for anomalies that block but don't log (highest risk)
        for anomaly in anomalies:
            if (
                anomaly.get("status") == "enable"
                and anomaly.get("action") in ("block", "quarantine")
                and anomaly.get("log") != "enable"
            ):
                anomaly_findings.append(DosAnomalyFinding(
                    anomaly_name=anomaly.get("name", "unknown"),
                    severity="high",
                    message=f"Anomaly '{anomaly.get('name')}' blocks traffic but does not log — forensic visibility is lost",
                    remediation=f"Enable logging on the '{anomaly.get('name')}' anomaly",
                ))

        return DimensionScore(
            dimension="logging",
            score=max(0, score),
            findings=findings,
            anomaly_findings=anomaly_findings,
        )

    def _score_policy_scope(self, policy: dict) -> DimensionScore:
        """Score based on address and service specificity (0-100).

        FortiGate DoS policies use ``srcaddr`` / ``dstaddr`` (address object
        lists) rather than ``src`` / ``dst`` (interface lists).  We check both
        naming conventions for backward compatibility.
        """
        findings: list[str] = []
        score = 100

        src = policy.get("srcaddr") or policy.get("src") or []
        dst = policy.get("dstaddr") or policy.get("dst") or []
        service = policy.get("service") or []

        # Normalize: items may be dicts with "name" or plain strings
        def _names(lst):
            return [
                item.get("name", "") if isinstance(item, dict) else str(item)
                for item in lst
            ]

        src_names = _names(src)
        dst_names = _names(dst)

        # Check source addresses
        if not src_names:
            score -= 15
            findings.append("No source address filter — policy applies to all sources")
        elif any(n.lower() == "all" for n in src_names if n):
            score -= 10
            findings.append("Source is set to 'all' — consider restricting to specific addresses")

        # Check destination addresses
        if not dst_names:
            score -= 15
            findings.append("No destination address filter — policy applies to all destinations")
        elif any(n.lower() == "all" for n in dst_names if n):
            score -= 10
            findings.append("Destination is set to 'all' — consider restricting to specific addresses")

        # Check service filter
        if not service:
            score -= 20
            findings.append("No service filter — policy inspects all traffic types, increasing processing load")

        return DimensionScore(
            dimension="policy_scope",
            score=max(0, score),
            findings=findings,
        )

    def _score_action(self, policy: dict, anomalies: list[dict]) -> DimensionScore:
        """Score based on per-anomaly action settings (0-100).

        FortiGate DoS policies have no policy-level ``action`` field.
        The action (pass / block / quarantine) is configured per-anomaly.
        """
        findings: list[str] = []
        anomaly_findings: list[DosAnomalyFinding] = []
        score = 100

        # Check per-anomaly actions
        for anomaly in anomalies:
            if anomaly.get("status") != "enable":
                continue
            name = anomaly.get("name", "")
            anomaly_action = anomaly.get("action", "pass")

            if name in CRITICAL_ANOMALIES and anomaly_action == "pass":
                anomaly_findings.append(DosAnomalyFinding(
                    anomaly_name=name,
                    severity="high",
                    message=f"Critical anomaly '{name}' is set to 'pass' — attacks will be detected but not blocked",
                    remediation=f"Change the '{name}' anomaly action to 'block' or 'quarantine'",
                ))
                score -= 15

        return DimensionScore(
            dimension="action",
            score=max(0, score),
            findings=findings,
            anomaly_findings=anomaly_findings,
        )
