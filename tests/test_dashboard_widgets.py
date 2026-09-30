"""Tests for the client dashboard widget layout."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.dashboard_widgets import (
    CATALOG_KEY,
    build_available_widgets,
    parse_layout,
    resolve_layout,
    sanitize_layout,
    serialize_layout,
)

ROOT = Path(__file__).resolve().parents[1]


def _svc(id_, service_type, name=None, description=""):
    return SimpleNamespace(id=id_, service_type=service_type, name=name or service_type, description=description)


@pytest.fixture
def available():
    return build_available_widgets([
        _svc(1, "policy_evaluation"),
        _svc(2, "dos_policy"),
        _svc(3, "something_new"),
    ])


def _keys(widgets):
    return [w["key"] for w in widgets]


class TestAvailableWidgets:
    def test_services_then_catalog(self, available):
        assert _keys(available) == ["service:1", "service:2", "service:3", CATALOG_KEY]

    def test_known_service_links_to_its_page(self, available):
        assert available[0]["endpoint"] == "client.policy_evaluation"
        assert available[1]["endpoint"] == "client.dos_policies"

    def test_unknown_service_type_is_coming_soon(self, available):
        assert available[2]["endpoint"] is None
        assert available[2]["cta"] == "Coming Soon"

    def test_admin_description_wins_over_default(self):
        widgets = build_available_widgets([_svc(1, "dos_policy", description="Custom text")])
        assert widgets[0]["description"] == "Custom text"

    def test_no_services_still_offers_catalog(self):
        assert _keys(build_available_widgets([])) == [CATALOG_KEY]


class TestParseLayout:
    def test_null_means_never_customised(self):
        assert parse_layout(None) is None

    @pytest.mark.parametrize("raw", ["not json", "{}", '"x"', "42"])
    def test_corrupt_values_fall_back_to_default(self, raw):
        assert parse_layout(raw) is None

    def test_empty_list_is_a_real_layout(self):
        assert parse_layout("[]") == []

    def test_non_string_entries_are_dropped(self):
        assert parse_layout('["a", 1, null, "b"]') == ["a", "b"]


class TestSanitizeLayout:
    def test_drops_unknown_and_duplicates_keeping_order(self, available):
        out = sanitize_layout(["service:2", "bogus", "service:2", CATALOG_KEY, 5], available)
        assert out == ["service:2", CATALOG_KEY]

    def test_rejects_non_list(self, available):
        with pytest.raises(ValueError):
            sanitize_layout("service:1", available)


class TestResolveLayout:
    def test_default_shows_everything(self, available):
        shown, hidden = resolve_layout(available, None)
        assert _keys(shown) == _keys(available)
        assert hidden == []

    def test_saved_order_and_hidden_split(self, available):
        shown, hidden = resolve_layout(available, serialize_layout([CATALOG_KEY, "service:1"]))
        assert _keys(shown) == [CATALOG_KEY, "service:1"]
        assert _keys(hidden) == ["service:2", "service:3"]

    def test_empty_layout_shows_nothing(self, available):
        shown, hidden = resolve_layout(available, "[]")
        assert shown == []
        assert _keys(hidden) == _keys(available)

    def test_stale_keys_for_lost_access_are_ignored(self):
        # user previously pinned service:9, but is no longer subscribed
        available = build_available_widgets([_svc(1, "dos_policy")])
        shown, _ = resolve_layout(available, serialize_layout(["service:9", "service:1"]))
        assert _keys(shown) == ["service:1"]

    def test_newly_subscribed_service_appears_in_tray_not_dashboard(self):
        available = build_available_widgets([_svc(1, "dos_policy"), _svc(2, "policy_evaluation")])
        shown, hidden = resolve_layout(available, serialize_layout(["service:1"]))
        assert _keys(shown) == ["service:1"]
        assert "service:2" in _keys(hidden)


def test_end_to_end_layout_flow(tmp_path):
    """Drive the real app (login, render, save, reset) against a temp SQLite DB."""
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path}/e2e.db", APP_ENV="development")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "_dashboard_e2e_script.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:] + proc.stdout[-2000:]
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULTS="))
    r = json.loads(line[len("RESULTS="):])
    eval_key, dos_key, risk_key = (f"service:{r['ids'][k]}" for k in ("eval", "dos", "risk"))

    # alice: two subscriptions + catalog, all visible by default
    assert r["default_all_keys"] == [eval_key, dos_key, CATALOG_KEY]
    assert r["default_hidden"] == []

    # custom order is honoured and the removed card sits in the hidden tray
    assert r["save_status"] == 200
    assert r["custom_all_keys"][:2] == [dos_key, CATALOG_KEY]
    assert r["custom_hidden"] == [eval_key]

    # a service she is not subscribed to (or unknown keys) can never be stored
    assert r["foreign_status"] == 200
    assert json.loads(r["stored_after_foreign"]) == [dos_key]
    assert risk_key not in r["custom_all_keys"]

    # malformed input is a clean 400
    assert r["bad_json"] == 400
    assert r["bad_layout_type"] == 400

    # layouts are per user
    assert r["bob_keys"] == [eval_key, CATALOG_KEY]
    assert r["bob_hidden"] == []

    # reset returns to "never customised"; anonymous users are refused
    assert r["stored_after_reset"] is None
    assert r["anon_status"] in (302, 401)

    # an intentionally empty dashboard is remembered, not reset to default
    assert r["empty_visible"] == []

    # CSRF: rejected and nothing saved
    assert r["csrf_rejected"] is True
    assert r["stored_after_csrf_reject"] == "[]"
