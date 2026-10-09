"""Service matching regressions: ALL service and multi-entry port ranges."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.fortigate_collector import publish_snapshot
from engine.evaluator import SecureTrackLite


class _Args:
    vdom = "root"
    scheme = "https"
    host = "fw.example"
    verify = True
    skip_monitor_routes = False


def _engine(tmp_path, policies, services):
    dataset = {
        "policies.json": policies,
        "addresses.json": [
            {"name": "all", "type": "ipmask", "subnet": "0.0.0.0 0.0.0.0"},
            {"name": "lan", "type": "ipmask", "subnet": "10.1.0.0 255.255.0.0"},
            {"name": "web", "type": "ipmask", "subnet": "10.2.2.10 255.255.255.255"},
        ],
        "services.json": services,
        "routes.json": [
            {"dst": "10.1.0.0/16", "device": "lan", "status": "enable"},
            {"dst": "10.2.2.0/24", "device": "dmz", "status": "enable"},
        ],
        "interfaces.json": [],
    }
    publish_snapshot(tmp_path, dataset, _Args)
    return SecureTrackLite(str(tmp_path))


def _policy(pid, service):
    return {
        "policyid": pid,
        "name": f"p{pid}",
        "action": "accept",
        "status": "enable",
        "srcaddr": [{"name": "lan"}],
        "dstaddr": [{"name": "web"}],
        "service": [{"name": service}],
        "srcintf": [{"name": "lan"}],
        "dstintf": [{"name": "dmz"}],
    }


def test_all_service_policy_covers_any_port(tmp_path):
    engine = _engine(
        tmp_path,
        [_policy(1, "ALL")],
        [{"name": "ALL", "protocol": "IP", "protocol-number": 0}],
    )
    results = engine.evaluate(["10.1.5.5"], ["10.2.2.10"], ["443"])
    assert [r["policyid"] for r in results] == [1]


def test_multi_entry_port_list_is_matched(tmp_path):
    engine = _engine(
        tmp_path,
        [_policy(2, "WEB")],
        [{"name": "WEB", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "80 443 8000-8080"}],
    )
    for port in ("80", "443", "tcp-8050"):
        results = engine.evaluate(["10.1.5.5"], ["10.2.2.10"], [port])
        assert [r["policyid"] for r in results] == [2], port
    assert engine.evaluate(["10.1.5.5"], ["10.2.2.10"], ["22"]) == []


def test_source_port_suffix_is_ignored(tmp_path):
    engine = _engine(
        tmp_path,
        [_policy(3, "HTTPS")],
        [{"name": "HTTPS", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "443:1024-65535"}],
    )
    results = engine.evaluate(["10.1.5.5"], ["10.2.2.10"], ["443"])
    assert [r["policyid"] for r in results] == [3]


def test_protocol_ip_with_protocol_number_is_not_wildcard(tmp_path):
    engine = _engine(
        tmp_path,
        [_policy(4, "GRE")],
        [{"name": "GRE", "protocol": "IP", "protocol-number": 47}],
    )
    assert engine.evaluate(["10.1.5.5"], ["10.2.2.10"], ["443"]) == []
