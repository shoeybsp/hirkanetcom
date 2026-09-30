"""Tests for DoS policy service, FortiGate client, and audit engine."""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.fortigate_client import FortiGateClient, FortiGateApiError
from engine.dos_policy_auditor import (
    DosPolicyAuditor,
    DosPolicyAuditResult,
    CRITICAL_ANOMALIES,
    RECOMMENDED_ANOMALIES,
)
from services.dos_policy import DosPolicyService, DosPolicyServiceError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SAMPLE_DOS_POLICY = {
    "id": 1,
    "policyid": 1,
    "name": "Test DoS Policy",
    "status": "enable",
    "srcaddr": [{"name": "all"}],
    "dstaddr": [{"name": "all"}],
    "service": [{"name": "ALL"}],
    "interface": {"q_origin_key": "port2"},
    "anomaly": [
        {"name": "tcp_syn_flood", "status": "enable", "action": "block", "threshold": 2000, "log": "enable", "quarantine": "none", "quarantine-expiry": "5m", "quarantine-log": "disable"},
        {"name": "icmp_flood", "status": "enable", "action": "block", "threshold": 10, "log": "enable", "quarantine": "none", "quarantine-expiry": "5m", "quarantine-log": "disable"},
        {"name": "udp_flood", "status": "enable", "action": "block", "threshold": 2000, "log": "enable", "quarantine": "none", "quarantine-expiry": "5m", "quarantine-log": "disable"},
    ],
}

SAMPLE_POLICY_LIST_RESPONSE = {
    "results": [SAMPLE_DOS_POLICY],
    "vdom": "root",
    "status": "success",
}

SAMPLE_POLICY_DETAIL_RESPONSE = {
    "results": [SAMPLE_DOS_POLICY],
    "vdom": "root",
}


def _mock_device(**overrides):
    """Build a mock Device model with sensible defaults."""
    device = MagicMock()
    device.id = overrides.get("id", 1)
    device.name = overrides.get("name", "Test Device")
    device.device_type = overrides.get("device_type", "fortigate")
    device.api_host = overrides.get("api_host", "192.168.1.1")
    device.api_scheme = overrides.get("api_scheme", "https")
    device.vdom = overrides.get("vdom", "root")
    device.verify_ssl = overrides.get("verify_ssl", False)
    device.timeout_seconds = overrides.get("timeout_seconds", 30)
    device.api_key_encrypted = overrides.get("api_key_encrypted", "encrypted-key")
    return device


# ---------------------------------------------------------------------------
# FortiGateClient tests
# ---------------------------------------------------------------------------
class TestFortiGateClient:
    """Test the FortiGate API client."""

    def test_build_session_sets_auth_header(self):
        client = FortiGateClient("192.168.1.1", "test-token")
        assert client._session.headers["Authorization"] == "Bearer test-token"
        client.close()

    def test_build_session_retries(self):
        client = FortiGateClient("192.168.1.1", "test-token")
        adapter = client._session.get_adapter("https://192.168.1.1")
        assert adapter.max_retries.total == 3
        client.close()

    def test_cmdb_url_construction(self):
        client = FortiGateClient("192.168.1.1", "token", scheme="https", vdom="root")
        url = client._cmdb_url("firewall/DoS-policy")
        assert url == "https://192.168.1.1/api/v2/cmdb/firewall/DoS-policy"
        client.close()

    def test_cmdb_url_strips_trailing_slash(self):
        client = FortiGateClient("192.168.1.1/", "token")
        url = client._cmdb_url("firewall/DoS-policy")
        assert "//" not in url.split("://", 1)[1]
        client.close()

    @patch.object(FortiGateClient, "_build_session")
    def test_list_dos_policies(self, mock_build):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_POLICY_LIST_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_build.return_value = mock_session

        client = FortiGateClient("192.168.1.1", "token")
        result = client.list_dos_policies()
        assert len(result) == 1
        assert result[0]["name"] == "Test DoS Policy"
        client.close()

    @patch.object(FortiGateClient, "_build_session")
    def test_get_dos_policy(self, mock_build):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_POLICY_DETAIL_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_build.return_value = mock_session

        client = FortiGateClient("192.168.1.1", "token")
        result = client.get_dos_policy(1)
        assert result is not None
        assert result["name"] == "Test DoS Policy"
        client.close()

    @patch.object(FortiGateClient, "_build_session")
    def test_get_dos_policy_not_found(self, mock_build):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        error = FortiGateApiError("Not found", status_code=404)
        mock_session.get.side_effect = error
        mock_build.return_value = mock_session

        client = FortiGateClient("192.168.1.1", "token")
        result = client.get_dos_policy(999)
        assert result is None
        client.close()

    def test_short_error_messages(self):
        import requests

        exc = requests.exceptions.SSLError("TLS error")
        msg = FortiGateClient._short_error(exc)
        assert "TLS" in msg

        exc = requests.exceptions.ConnectTimeout("Timeout")
        msg = FortiGateClient._short_error(exc)
        assert "timed out" in msg.lower()

        exc = requests.exceptions.ConnectionError("Refused")
        msg = FortiGateClient._short_error(exc)
        assert "connect" in msg.lower()


# ---------------------------------------------------------------------------
# DosPolicyAuditor tests
# ---------------------------------------------------------------------------
class TestDosPolicyAuditor:
    """Test the DoS policy audit engine."""

    def test_audit_all_enabled_policy(self):
        """A policy with all critical anomalies enabled should score well."""
        policy = {
            "id": 1,
            "name": "Good Policy",
            "status": "enable",
            "srcaddr": [{"name": "all"}],
            "dstaddr": [{"name": "all"}],
            "service": [{"name": "ALL"}],
            "anomaly": [
                {"name": "tcp_syn_flood", "status": "enable", "action": "block", "threshold": 1000, "log": "enable"},
                {"name": "icmp_flood", "status": "enable", "action": "block", "threshold": 500, "log": "enable"},
                {"name": "udp_flood", "status": "enable", "action": "block", "threshold": 500, "log": "enable"},
            ],
        }
        auditor = DosPolicyAuditor([policy])
        results = auditor.audit()
        assert len(results) == 1
        assert results[0].audit_score > 50  # Should have a reasonable score
        assert results[0].risk_level in ("low", "info", "medium")

    def test_audit_disabled_critical_anomalies(self):
        """A policy with critical anomalies disabled should score poorly."""
        policy = {
            "id": 1,
            "name": "Bad Policy",
            "status": "enable",
            "srcaddr": [],
            "dstaddr": [],
            "service": [],
            "anomaly": [],
        }
        auditor = DosPolicyAuditor([policy])
        results = auditor.audit()
        assert len(results) == 1
        assert results[0].audit_score < 50
        assert results[0].risk_level in ("critical", "high", "medium")

    def test_audit_no_logging(self):
        """A policy with logging disabled should lose points."""
        policy = {
            "id": 1,
            "name": "No Logging",
            "status": "enable",
            "srcaddr": [{"name": "all"}],
            "dstaddr": [{"name": "all"}],
            "service": [{"name": "ALL"}],
            "anomaly": [
                {"name": "tcp_syn_flood", "status": "enable", "action": "block", "log": "disable"},
            ],
        }
        auditor = DosPolicyAuditor([policy])
        results = auditor.audit()
        # Should have logging-related findings
        all_findings = []
        for dim in results[0].dimensions:
            all_findings.extend(dim.findings)
        assert any("logging" in f.lower() for f in all_findings)

    def test_audit_summary(self):
        """Summary should reflect counts correctly."""
        policies = [
            {"id": 1, "name": "P1", "status": "enable", "anomaly": [], "srcaddr": [{"name": "a"}], "dstaddr": [{"name": "b"}], "service": [{"name": "c"}]},
            {"id": 2, "name": "P2", "status": "disable", "anomaly": [], "srcaddr": [], "dstaddr": [], "service": []},
        ]
        auditor = DosPolicyAuditor(policies)
        auditor.audit()
        summary = auditor.get_summary()
        assert summary["total_policies"] == 2
        assert summary["enabled_count"] == 1
        assert summary["disabled_count"] == 1
        assert "avg_score" in summary
        assert "risk_counts" in summary

    def test_audit_single(self):
        """Audit a single policy by ID."""
        policies = [
            {"id": 1, "name": "P1", "status": "enable", "anomaly": [], "srcaddr": [], "dstaddr": [], "service": []},
            {"id": 2, "name": "P2", "status": "enable", "anomaly": [], "srcaddr": [], "dstaddr": [], "service": []},
        ]
        auditor = DosPolicyAuditor(policies)
        result = auditor.audit_single(2)
        assert result is not None
        assert result.name == "P2"

    def test_audit_single_not_found(self):
        """Audit a single policy by nonexistent ID."""
        auditor = DosPolicyAuditor([{"id": 1, "name": "P1", "status": "enable", "anomaly": [], "srcaddr": [], "dstaddr": [], "service": []}])
        result = auditor.audit_single(999)
        assert result is None

    def test_empty_policies(self):
        """Audit with no policies."""
        auditor = DosPolicyAuditor([])
        results = auditor.audit()
        assert results == []
        summary = auditor.get_summary()
        assert summary["total_policies"] == 0


# ---------------------------------------------------------------------------
# DosPolicyService tests
# ---------------------------------------------------------------------------
class TestDosPolicyService:
    """Test the DoS policy service layer."""

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    def test_build_client_success(self, mock_decrypt):
        device = _mock_device()
        client = DosPolicyService._build_client(device)
        assert client is not None
        assert isinstance(client, FortiGateClient)
        client.close()

    @patch("services.dos_policy.decrypt_secret", return_value="")
    def test_build_client_no_token(self, mock_decrypt):
        device = _mock_device()
        with pytest.raises(DosPolicyServiceError, match="no API key"):
            DosPolicyService._build_client(device)

    def test_build_client_wrong_type(self):
        device = _mock_device(device_type="paloalto")
        with pytest.raises(DosPolicyServiceError, match="not supported"):
            DosPolicyService._build_client(device)

    def test_build_client_no_host(self):
        device = _mock_device(api_host="")
        with pytest.raises(DosPolicyServiceError, match="no API host"):
            DosPolicyService._build_client(device)

    @patch("services.dos_policy.decrypt_secret")
    def test_build_client_decrypt_error(self, mock_decrypt):
        from secret_crypto import CredentialEncryptionError
        mock_decrypt.side_effect = CredentialEncryptionError("bad key")
        device = _mock_device()
        with pytest.raises(DosPolicyServiceError):
            DosPolicyService._build_client(device)

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    @patch.object(FortiGateClient, "list_dos_policies", return_value=[SAMPLE_DOS_POLICY])
    def test_list_policies(self, mock_list, mock_decrypt):
        device = _mock_device()
        svc = DosPolicyService(device)
        result = svc.list_policies()
        assert result.total == 1
        assert result.data[0]["name"] == "Test DoS Policy"
        assert result.device_id == 1
        svc.close()

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    @patch.object(FortiGateClient, "get_dos_policy", return_value=SAMPLE_DOS_POLICY)
    def test_get_policy(self, mock_get, mock_decrypt):
        device = _mock_device()
        svc = DosPolicyService(device)
        result = svc.get_policy(1)
        assert result is not None
        assert result["name"] == "Test DoS Policy"
        svc.close()

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    @patch.object(FortiGateClient, "list_dos_policies", return_value=[SAMPLE_DOS_POLICY])
    def test_audit_policies(self, mock_list, mock_decrypt):
        device = _mock_device()
        svc = DosPolicyService(device)
        result = svc.audit_policies()
        assert len(result.data) == 1
        assert result.device_id == 1
        svc.close()

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    @patch.object(FortiGateClient, "list_dos_policies", side_effect=FortiGateApiError("Connection refused"))
    def test_audit_policies_api_error(self, mock_list, mock_decrypt):
        device = _mock_device()
        svc = DosPolicyService(device)
        with pytest.raises(DosPolicyServiceError):
            svc.audit_policies()
        svc.close()

    @patch("services.dos_policy.decrypt_secret", return_value="test-token")
    def test_context_manager(self, mock_decrypt):
        device = _mock_device()
        with DosPolicyService(device) as svc:
            assert svc is not None


# ---------------------------------------------------------------------------
# Regression tests for the DoS policy bug-verification pass
# ---------------------------------------------------------------------------
class TestAuditorHardening:
    def test_audit_single_ignores_non_numeric_ids(self):
        auditor = DosPolicyAuditor([{"id": "abc", "name": "x"}, {"id": "2", "name": "y"}])
        assert auditor.audit_single(2).name == "y"
        assert auditor.audit_single(1) is None

    def test_audit_tolerates_non_numeric_id(self):
        result = DosPolicyAuditor([{"id": "abc", "name": "x"}]).audit()[0]
        assert result.policy_id is None

    def test_no_enabled_anomalies_is_not_low_risk(self):
        result = DosPolicyAuditor([{"id": 1, "name": "x", "anomaly": []}]).audit()[0]
        assert result.risk_level in ("critical", "high")


class TestListDosPoliciesShapes:
    @patch.object(FortiGateClient, "_build_session")
    def test_dict_result_is_wrapped(self, mock_build):
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {"results": {"policyid": 3, "name": "solo"}}
        response.raise_for_status = MagicMock()
        session.get.return_value = response
        mock_build.return_value = session
        client = FortiGateClient("192.168.1.1", "token")
        result = client.list_dos_policies()
        assert [p["id"] for p in result] == [3]
        client.close()


class TestReadOnly:
    """The DoS policy feature only lists and audits; nothing writes to the device."""

    def test_service_has_no_write_methods(self):
        for name in ("create_policy", "update_policy", "delete_policy"):
            assert not hasattr(DosPolicyService, name)

    def test_client_has_no_write_methods(self):
        for name in ("post", "put", "delete", "create_dos_policy",
                     "update_dos_policy", "delete_dos_policy"):
            assert not hasattr(FortiGateClient, name)

    def test_write_routes_are_gone(self):
        import re
        from pathlib import Path
        src = Path("client/routes.py").read_text()
        for fragment in ("/dos-policies/create", "/edit", "/delete", "dos_policy_form"):
            assert not re.search(re.escape(fragment), src.split("DoS Policy Service")[-1])
        assert not Path("templates/client/dos_policy_form.html").exists()
