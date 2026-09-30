"""Reusable FortiGate REST API client.

Provides authenticated HTTP access to the FortiGate CMDB API with
retry logic, structured error handling, and read-only DoS-policy
convenience methods.  The client is stateless after construction;
each instance holds one set of connection parameters and an
authenticated ``requests.Session``.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_DOS_POLICY_PATH = "firewall/DoS-policy"
_MAX_ERROR_MESSAGE_LENGTH = 500


class FortiGateApiError(RuntimeError):
    """The FortiGate API returned an error or could not be reached."""

    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class FortiGateClient:
    """Authenticated client for the FortiGate REST API.

    Parameters match the fields stored on a ``Device`` row so the
    service layer can build one directly from a device object.
    """

    def __init__(
        self,
        api_host: str,
        api_key: str,
        *,
        scheme: str = "https",
        vdom: str = "root",
        verify_ssl: bool = False,
        timeout: int = 30,
    ):
        self.api_host = api_host.rstrip("/")
        self.api_key = api_key
        self.scheme = scheme
        self.vdom = vdom
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._session = self._build_session()

    # -- Session setup --------------------------------------------------------

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session

    # -- URL helpers ----------------------------------------------------------

    def _base_url(self) -> str:
        host = self.api_host
        if not host.startswith(("http://", "https://")):
            host = f"{self.scheme}://{host}"
        return host

    def _cmdb_url(self, cmdb_path: str) -> str:
        return f"{self._base_url()}/api/v2/cmdb/{cmdb_path}"

    # -- Low-level HTTP -------------------------------------------------------

    def get(self, cmdb_path: str, **extra_params: Any) -> dict:
        """Send a GET request and return the parsed JSON body."""
        params = {"vdom": self.vdom, **extra_params}
        try:
            response = self._session.get(
                self._cmdb_url(cmdb_path),
                params=params,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            raise FortiGateApiError(self._short_error(exc), status_code=status) from exc

    # -- DoS Policy methods ---------------------------------------------------

    @staticmethod
    def _extract_results(payload: dict) -> list | dict | None:
        """Extract the results list/dict from a FortiGate API response.

        The DoS-policy endpoint (and some firmware versions) may return
        the payload under either ``"results"`` or ``"data"``.
        """
        for key in ("results", "data"):
            value = payload.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _normalize_dos_policy(policy: dict) -> dict:
        """Ensure every DoS policy dict has an ``id`` key.

        Different FortiGate firmware versions use different primary keys
        for DoS policies (``policyid``, ``seq-num``, ``seqnum``).  We
        copy whichever one is present to ``id`` so callers (JS, routes)
        can use a consistent field.
        """
        if "id" not in policy:
            for key in ("policyid", "seq-num", "seqnum"):
                if key in policy:
                    policy["id"] = policy[key]
                    break
        return policy

    def list_dos_policies(self) -> list[dict]:
        """Return all DoS policies for the configured VDOM."""
        payload = self.get(_DOS_POLICY_PATH)
        raw = self._extract_results(payload)
        if isinstance(raw, dict):
            raw = [raw]  # a single policy object returned for a list call
        policies = [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []
        return [self._normalize_dos_policy(p) for p in policies]

    def get_dos_policy(self, policy_id: int) -> dict | None:
        """Return a single DoS policy by its seq-num, or ``None`` if not found."""
        try:
            payload = self.get(f"{_DOS_POLICY_PATH}/{policy_id}")
            raw = self._extract_results(payload)
            if isinstance(raw, list) and raw:
                return self._normalize_dos_policy(raw[0])
            if isinstance(raw, dict):
                return self._normalize_dos_policy(raw)
            return None
        except FortiGateApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    # -- Utilities ------------------------------------------------------------

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """Produce a concise, non-leaky description of an API failure."""
        import requests as _requests

        if isinstance(exc, _requests.exceptions.SSLError):
            message = "TLS verification failed. Check 'Verify TLS certificate' setting."
        elif isinstance(exc, _requests.exceptions.ConnectTimeout):
            message = "Connection timed out. Check the API host and network reachability."
        elif isinstance(exc, _requests.exceptions.ConnectionError):
            message = "Could not connect to the device. Check the API host and port."
        elif isinstance(exc, _requests.exceptions.HTTPError):
            status = getattr(exc.response, "status_code", None)
            if status in (401, 403):
                message = f"Device rejected the API key (HTTP {status}). Check the key and its trusted hosts / profile."
            elif status == 404:
                message = "API path not found (HTTP 404). Check the VDOM and the device firmware version."
            else:
                message = f"Device returned HTTP {status}." if status else "Device returned an HTTP error."
        elif isinstance(exc, _requests.exceptions.RequestException):
            message = "The request to the device failed."
        else:
            message = str(exc) or exc.__class__.__name__
        return message[:_MAX_ERROR_MESSAGE_LENGTH]

    def close(self):
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
