"""Tests for the on-demand device sync service."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "development")

import secret_crypto  # noqa: E402
from collectors import sync_service  # noqa: E402


def make_device(**overrides):
    """Build a Device-like object without needing a database session."""
    values = dict(
        id=1,
        name="Test FGT",
        device_type="fortigate",
        api_host="192.0.2.10",
        api_scheme="https",
        vdom="root",
        verify_ssl=False,
        timeout_seconds=30,
        skip_monitor_routes=False,
        keep_snapshots=10,
        data_dir="data/devices/test",
        api_key_encrypted=secret_crypto.encrypt_secret("tok_test"),
        last_sync_at=None,
        last_sync_status=None,
        last_sync_message=None,
        last_snapshot_id=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_collector_args_decrypts_credentials_and_maps_settings():
    device = make_device(vdom="vd1", timeout_seconds=15, keep_snapshots=4, verify_ssl=True)
    args = sync_service.build_collector_args(device)

    assert args.token == "tok_test"
    assert args.host == "192.0.2.10"
    assert args.vdom == "vd1"
    assert args.timeout == 15
    assert args.keep_snapshots == 4
    assert args.verify is True


def test_relative_data_dir_resolves_under_project_root():
    device = make_device(data_dir="data/devices/abc")
    root = sync_service.resolve_device_data_root(device)
    assert root.is_absolute()
    assert root == ROOT / "data" / "devices" / "abc"


def test_absolute_data_dir_is_preserved():
    device = make_device(data_dir="/srv/snapshots/abc")
    assert sync_service.resolve_device_data_root(device) == Path("/srv/snapshots/abc")


def test_missing_api_key_is_rejected_before_any_network_call():
    device = make_device(api_key_encrypted=None)
    with pytest.raises(sync_service.DeviceSyncError, match="no API key"):
        sync_service.build_collector_args(device)


def test_missing_api_host_is_rejected():
    device = make_device(api_host="")
    with pytest.raises(sync_service.DeviceSyncError, match="no API host"):
        sync_service.build_collector_args(device)


def test_unsupported_device_type_is_rejected():
    device = make_device(device_type="paloalto")
    with pytest.raises(sync_service.DeviceSyncError, match="not supported"):
        sync_service.build_collector_args(device)


def test_failed_precondition_records_failure_status_on_device():
    device = make_device(api_key_encrypted=None)
    with pytest.raises(sync_service.DeviceSyncError):
        sync_service.run_device_sync(device)

    assert device.last_sync_status == "failure"
    assert device.last_sync_at is not None
    assert "no API key" in device.last_sync_message


def test_error_messages_are_actionable_and_do_not_leak_raw_payloads():
    response = SimpleNamespace(status_code=401)
    http_error = requests.exceptions.HTTPError("401 for url https://host/api?access_token=SECRET")
    http_error.response = response

    message = sync_service._short_error(http_error)
    assert "401" in message
    assert "SECRET" not in message
    assert "access_token" not in message


def test_error_messages_are_length_bounded():
    message = sync_service._short_error(RuntimeError("x" * 5000))
    assert len(message) <= sync_service._MAX_SYNC_MESSAGE_LENGTH


def test_tls_failure_explains_the_verify_setting():
    message = sync_service._short_error(requests.exceptions.SSLError("bad handshake"))
    assert "TLS" in message
    assert "Verify TLS certificate" in message
