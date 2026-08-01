import json

from engine.cidr_tools import any_overlap, is_covered_by, range_spec
from engine.evaluator import SecureTrackLite


def test_range_boundaries_are_inclusive():
    policy_range = range_spec("192.0.2.10", "192.0.2.50")
    assert is_covered_by("192.0.2.10/32", policy_range)
    assert is_covered_by("192.0.2.50/32", policy_range)
    assert not is_covered_by("192.0.2.9/32", policy_range)
    assert not is_covered_by("192.0.2.51/32", policy_range)


def test_requested_subnet_must_be_fully_covered_by_range():
    policy_range = range_spec("192.0.2.10", "192.0.2.50")
    assert is_covered_by("192.0.2.16/28", policy_range)
    assert not is_covered_by("192.0.2.0/27", policy_range)


def test_range_can_be_covered_by_network_or_another_range():
    requested = range_spec("198.51.100.20", "198.51.100.30")
    assert is_covered_by(requested, "198.51.100.0/24")
    assert is_covered_by(requested, range_spec("198.51.100.10", "198.51.100.40"))
    assert not is_covered_by(requested, range_spec("198.51.100.25", "198.51.100.40"))


def test_overlap_supports_networks_and_ranges():
    address_range = range_spec("203.0.113.10", "203.0.113.20")
    assert any_overlap(address_range, "203.0.113.16/28")
    assert not any_overlap(address_range, "203.0.113.32/28")


def test_evaluator_preserves_full_collected_range(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "addresses.json").write_text(json.dumps([
        {"name": "server-range", "type": "iprange", "iprange": "10.0.0.10 10.0.0.20"},
        {"name": "client", "subnet": "192.0.2.1 255.255.255.255"},
    ]))
    (data_dir / "services.json").write_text(json.dumps([
        {"name": "HTTPS", "tcp-portrange": "443"}
    ]))
    (data_dir / "policies.json").write_text(json.dumps([
        {
            "policyid": 1,
            "name": "range-policy",
            "action": "accept",
            "status": "enable",
            "srcaddr": [{"name": "client"}],
            "dstaddr": [{"name": "server-range"}],
            "service": [{"name": "HTTPS"}],
            "srcintf": [{"name": "any"}],
            "dstintf": [{"name": "any"}],
        }
    ]))
    (data_dir / "routes.json").write_text("[]")
    monkeypatch.chdir(tmp_path)

    evaluator = SecureTrackLite()
    assert evaluator.addr_map["server-range"] == {
        "kind": "range",
        "start": "10.0.0.10",
        "end": "10.0.0.20",
    }

    inside = evaluator.evaluate(["client"], ["10.0.0.20"], ["https"])
    outside = evaluator.evaluate(["client"], ["10.0.0.21"], ["https"])

    assert inside[0]["dst_matches"] == 1
    assert inside[0]["candidate_action"] == "already covered"
    assert outside == []


def test_named_range_request_is_fully_checked(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "addresses.json").write_text(json.dumps([
        {"name": "requested-range", "type": "iprange", "iprange": "10.0.0.10 10.0.0.20"},
        {"name": "too-small", "type": "iprange", "iprange": "10.0.0.10 10.0.0.15"},
        {"name": "client", "subnet": "192.0.2.1 255.255.255.255"},
    ]))
    (data_dir / "services.json").write_text("[]")
    (data_dir / "policies.json").write_text(json.dumps([
        {
            "policyid": 2,
            "name": "small-range-policy",
            "action": "accept",
            "status": "enable",
            "srcaddr": [{"name": "client"}],
            "dstaddr": [{"name": "too-small"}],
            "service": [],
            "srcintf": [{"name": "any"}],
            "dstintf": [{"name": "any"}],
        }
    ]))
    (data_dir / "routes.json").write_text("[]")
    monkeypatch.chdir(tmp_path)

    evaluator = SecureTrackLite()
    assert evaluator.evaluate(["client"], ["requested-range"], []) == []
