"""Tests for device selection and authorization in policy evaluation."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "development")

from client.routes import resolve_selected_device  # noqa: E402


def device(device_id, name="Device"):
    return SimpleNamespace(id=device_id, name=name)


def test_no_assigned_devices_is_refused():
    selected, error = resolve_selected_device("1", [])
    assert selected is None
    assert "No devices" in error


def test_blank_selection_defaults_to_first_assigned_device():
    devices = [device(4, "A"), device(9, "B")]
    selected, error = resolve_selected_device("", devices)
    assert error is None
    assert selected.id == 4


def test_missing_selection_defaults_to_first_assigned_device():
    devices = [device(4, "A")]
    selected, error = resolve_selected_device(None, devices)
    assert error is None
    assert selected.id == 4


def test_valid_selection_is_honoured():
    devices = [device(4, "A"), device(9, "B")]
    selected, error = resolve_selected_device("9", devices)
    assert error is None
    assert selected.id == 9


def test_unassigned_device_is_refused_even_when_it_exists():
    devices = [device(4, "A")]
    selected, error = resolve_selected_device("9", devices)
    assert selected is None
    assert "do not have access" in error


def test_non_numeric_selection_is_refused():
    devices = [device(4, "A")]
    selected, error = resolve_selected_device("../../etc/passwd", devices)
    assert selected is None
    assert "Invalid device selection" in error


def test_selection_authorizes_against_the_caller_supplied_list_only():
    """The device list is built from the user's own assignments, so a device
    absent from it must never be selectable regardless of its id."""
    devices = [device(2, "Assigned")]
    for attempted in ("3", "1", "999", "-1", "0"):
        selected, error = resolve_selected_device(attempted, devices)
        assert selected is None, f"device id {attempted} should not be selectable"
        assert error
