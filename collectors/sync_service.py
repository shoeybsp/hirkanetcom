"""Run the device collector on demand for a registered Device.

This bridges the admin "Sync Now" button to the existing collector script.
The collector's own functions are reused unchanged - they operate on a
simple attribute bag (previously produced by argparse), so this module
builds an equivalent object from a Device row instead of from CLI flags.
That keeps the standalone CLI entrypoint (and any cron jobs using it)
working exactly as before.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from collectors.fortigate_collector import (
    build_session,
    collect_dataset,
    collector_lock,
    prune_snapshots,
    publish_snapshot,
)
from secret_crypto import CredentialEncryptionError, decrypt_secret

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]

# Keep stored failure messages short and free of raw exception payloads,
# which can echo back request URLs or response bodies.
_MAX_SYNC_MESSAGE_LENGTH = 500


class DeviceSyncError(RuntimeError):
    """Raised when a device sync cannot be performed."""


@dataclass
class CollectorArgs:
    """Mirrors the argparse namespace the collector functions expect."""

    host: str
    token: str
    vdom: str
    scheme: str
    verify: bool
    timeout: int
    skip_monitor_routes: bool
    keep_snapshots: int
    output_dir: str


def resolve_device_data_root(device) -> Path:
    """Return the absolute snapshot directory for a device.

    Device.data_dir is stored relative to the project root so the value
    stays valid across container rebuilds and host/container path
    differences. Absolute values are honoured as-is.
    """
    data_dir = (device.data_dir or "").strip()
    if not data_dir:
        raise DeviceSyncError("Device has no data directory configured.")
    path = Path(data_dir)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def build_collector_args(device) -> CollectorArgs:
    """Build collector arguments from a device's stored configuration."""
    if device.device_type != "fortigate":
        raise DeviceSyncError(
            f"Syncing is not supported for device type '{device.device_type}'."
        )
    if not (device.api_host or "").strip():
        raise DeviceSyncError("Device has no API host configured.")

    try:
        token = decrypt_secret(device.api_key_encrypted)
    except CredentialEncryptionError as exc:
        raise DeviceSyncError(str(exc)) from exc
    if not token:
        raise DeviceSyncError("Device has no API key configured.")

    return CollectorArgs(
        host=device.api_host,
        token=token,
        vdom=device.vdom or "root",
        scheme=device.api_scheme or "https",
        verify=bool(device.verify_ssl),
        timeout=int(device.timeout_seconds or 30),
        skip_monitor_routes=bool(device.skip_monitor_routes),
        keep_snapshots=int(device.keep_snapshots or 10),
        output_dir=str(resolve_device_data_root(device)),
    )


def _short_error(exc: Exception) -> str:
    """Produce a concise, non-leaky description of a collection failure."""
    if isinstance(exc, requests.exceptions.SSLError):
        message = (
            "TLS verification failed. Uncheck 'Verify TLS certificate' if the "
            "device uses a self-signed certificate."
        )
    elif isinstance(exc, requests.exceptions.ConnectTimeout):
        message = "Connection timed out. Check the API host and network reachability."
    elif isinstance(exc, requests.exceptions.ConnectionError):
        message = "Could not connect to the device. Check the API host and port."
    elif isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(exc.response, "status_code", None)
        if status in (401, 403):
            message = f"Device rejected the API key (HTTP {status}). Check the key and its trusted hosts / profile."
        elif status == 404:
            message = "API path not found (HTTP 404). Check the VDOM and the device's firmware version."
        else:
            message = f"Device returned HTTP {status}." if status else "Device returned an HTTP error."
    elif isinstance(exc, requests.exceptions.RequestException):
        message = "The request to the device failed."
    else:
        message = str(exc) or exc.__class__.__name__
    return message[:_MAX_SYNC_MESSAGE_LENGTH]


def run_device_sync(device) -> dict:
    """Collect a fresh snapshot for a device and record the outcome.

    Returns a summary dict on success. On failure a DeviceSyncError is
    raised. In both cases the device's last_sync_* fields are updated; the
    caller is responsible for committing the surrounding transaction.
    """
    started_at = datetime.now(timezone.utc)

    try:
        args = build_collector_args(device)
    except DeviceSyncError as exc:
        device.last_sync_at = started_at
        device.last_sync_status = "failure"
        device.last_sync_message = str(exc)[:_MAX_SYNC_MESSAGE_LENGTH]
        raise

    if not args.verify:
        disable_warnings(InsecureRequestWarning)

    output_dir = Path(args.output_dir)
    session = build_session(args.token)

    try:
        with collector_lock(output_dir):
            dataset = collect_dataset(session, args)
            snapshot_id, snapshot_dir, manifest = publish_snapshot(output_dir, dataset, args)
            prune_snapshots(output_dir, snapshot_id, args.keep_snapshots)
    except Exception as exc:
        message = _short_error(exc)
        device.last_sync_at = datetime.now(timezone.utc)
        device.last_sync_status = "failure"
        device.last_sync_message = message
        logger.warning(
            "Device sync failed",
            extra={
                "event_type": "device_sync_failed",
                "device_id": str(device.id),
                "device_name": device.name,
            },
            exc_info=exc,
        )
        raise DeviceSyncError(message) from exc
    finally:
        session.close()

    record_counts = {name: entry["records"] for name, entry in manifest["files"].items()}
    total_records = sum(record_counts.values())

    device.last_sync_at = datetime.now(timezone.utc)
    device.last_sync_status = "success"
    device.last_snapshot_id = snapshot_id
    device.last_sync_message = (
        f"Collected {record_counts.get('policies.json', 0)} policies, "
        f"{record_counts.get('addresses.json', 0)} addresses, "
        f"{record_counts.get('services.json', 0)} services, "
        f"{record_counts.get('routes.json', 0)} routes, "
        f"{record_counts.get('interfaces.json', 0)} interfaces."
    )[:_MAX_SYNC_MESSAGE_LENGTH]

    duration = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "Device sync succeeded",
        extra={
            "event_type": "device_sync_succeeded",
            "device_id": str(device.id),
            "device_name": device.name,
            "snapshot_id": snapshot_id,
            "record_counts": record_counts,
            "duration_seconds": round(duration, 2),
        },
    )

    return {
        "snapshot_id": snapshot_id,
        "snapshot_dir": str(snapshot_dir),
        "record_counts": record_counts,
        "total_records": total_records,
        "duration_seconds": duration,
    }
