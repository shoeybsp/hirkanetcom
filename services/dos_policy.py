"""DoS policy management service.

Orchestrates the FortiGate API client and DoS policy audit engine to
provide a high-level, read-only interface for listing and auditing
DoS policies.  Each instance is bound to a single device and
holds a live API connection through the FortiGate client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from engine.fortigate_client import FortiGateClient, FortiGateApiError
from engine.dos_policy_auditor import (
    DosPolicyAuditor,
    DosPolicyAuditResult,
)
from secret_crypto import CredentialEncryptionError, decrypt_secret

logger = logging.getLogger(__name__)

_MAX_SERVICE_MESSAGE_LENGTH = 500


class DosPolicyServiceError(RuntimeError):
    """Raised when a DoS policy operation cannot be performed."""


@dataclass(frozen=True)
class DosPolicyListResult:
    """Container for a list of DoS policies with metadata."""

    data: list[dict[str, Any]]
    total: int
    device_id: int
    device_name: str


@dataclass(frozen=True)
class DosPolicyAuditResultContainer:
    """Container for audit results with summary."""

    data: list[DosPolicyAuditResult]
    summary: dict[str, Any]
    device_id: int
    device_name: str


class DosPolicyService:
    """High-level, read-only interface for DoS policies on a single device.

    Usage::

        svc = DosPolicyService(device)
        policies = svc.list_policies()
        audit = svc.audit_policies()
        svc.close()
    """

    def __init__(self, device):
        """Build a service from a ``Device`` model instance.

        Decrypts stored credentials and creates a ``FortiGateClient``.
        Raises ``DosPolicyServiceError`` if the device is misconfigured.
        """
        self._device = device
        self._client = self._build_client(device)
        self._auditor = DosPolicyAuditor()

    @staticmethod
    def _build_client(device) -> FortiGateClient:
        """Build an API client from a Device model's stored settings."""
        if device.device_type != "fortigate":
            raise DosPolicyServiceError(
                f"DoS policy management is not supported for device type '{device.device_type}'."
            )
        if not (device.api_host or "").strip():
            raise DosPolicyServiceError("Device has no API host configured.")

        try:
            token = decrypt_secret(device.api_key_encrypted)
        except CredentialEncryptionError as exc:
            raise DosPolicyServiceError(str(exc)) from exc
        if not token:
            raise DosPolicyServiceError("Device has no API key configured.")

        return FortiGateClient(
            api_host=device.api_host,
            api_key=token,
            scheme=device.api_scheme or "https",
            vdom=device.vdom or "root",
            verify_ssl=bool(device.verify_ssl),
            timeout=int(device.timeout_seconds or 30),
        )

    # -- Policy CRUD ----------------------------------------------------------

    def list_policies(self) -> DosPolicyListResult:
        """Fetch and return all DoS policies from the device."""
        try:
            policies = self._client.list_dos_policies()
        except FortiGateApiError as exc:
            logger.error("FortiGate DoS policy list error: %s", exc.response_body or str(exc))
            raise DosPolicyServiceError(self._short_error(str(exc))) from exc

        return DosPolicyListResult(
            data=policies,
            total=len(policies),
            device_id=self._device.id,
            device_name=self._device.name,
        )

    def get_policy(self, policy_id: int) -> dict[str, Any] | None:
        """Fetch a single DoS policy by ID."""
        try:
            return self._client.get_dos_policy(policy_id)
        except FortiGateApiError as exc:
            logger.error("FortiGate DoS policy get error: %s", exc.response_body or str(exc))
            raise DosPolicyServiceError(self._short_error(str(exc))) from exc

    # -- Audit ----------------------------------------------------------------

    def audit_policies(self) -> DosPolicyAuditResultContainer:
        """Fetch current policies and run the audit engine."""
        try:
            policies = self._client.list_dos_policies()
        except FortiGateApiError as exc:
            logger.error("FortiGate DoS policy audit error: %s", exc.response_body or str(exc))
            raise DosPolicyServiceError(self._short_error(str(exc))) from exc

        self._auditor.set_policies(policies)
        results = self._auditor.audit()
        summary = self._auditor.get_summary()

        return DosPolicyAuditResultContainer(
            data=results,
            summary=summary,
            device_id=self._device.id,
            device_name=self._device.name,
        )

    # -- Utilities ------------------------------------------------------------

    def close(self):
        """Close the underlying API client session."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _short_error(message: str) -> str:
        return message[:_MAX_SERVICE_MESSAGE_LENGTH]
