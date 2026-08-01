"""IPv4 network and FortiGate IP-range matching helpers."""

from __future__ import annotations

import ipaddress
from typing import Mapping


AddressSpec = str | Mapping[str, str]


def to_network(addr: str | None):
    if not addr or not isinstance(addr, str):
        return None
    try:
        if "/" not in addr:
            return ipaddress.ip_network(addr + "/32", strict=False)
        return ipaddress.ip_network(addr, strict=False)
    except ValueError:
        return None


def to_range(addr: AddressSpec | None):
    """Return inclusive IPv4 integer bounds for a network or range specification."""
    if not addr:
        return None

    if isinstance(addr, Mapping):
        if addr.get("kind") != "range":
            return None
        try:
            start = ipaddress.ip_address(addr["start"])
            end = ipaddress.ip_address(addr["end"])
        except (KeyError, ValueError):
            return None
        if start.version != 4 or end.version != 4 or int(start) > int(end):
            return None
        return int(start), int(end)

    network = to_network(addr)
    if not network or network.version != 4:
        return None
    return int(network.network_address), int(network.broadcast_address)


def range_spec(start: str, end: str):
    """Build a validated, JSON-serializable inclusive IPv4 range specification."""
    bounds = to_range({"kind": "range", "start": start, "end": end})
    if not bounds:
        return None
    normalized_start = str(ipaddress.ip_address(bounds[0]))
    normalized_end = str(ipaddress.ip_address(bounds[1]))
    return {"kind": "range", "start": normalized_start, "end": normalized_end}


def representative_ip(addr: AddressSpec | None):
    """Return the first IP as text for route lookup and proximity calculations."""
    bounds = to_range(addr)
    return str(ipaddress.ip_address(bounds[0])) if bounds else None


def is_subset(child: AddressSpec, parent: AddressSpec):
    child_bounds = to_range(child)
    parent_bounds = to_range(parent)
    return bool(
        child_bounds
        and parent_bounds
        and parent_bounds[0] <= child_bounds[0]
        and child_bounds[1] <= parent_bounds[1]
    )


def any_overlap(a: AddressSpec, b: AddressSpec):
    left = to_range(a)
    right = to_range(b)
    return bool(left and right and left[0] <= right[1] and right[0] <= left[1])


def is_covered_by(requested: AddressSpec, policy_addr: AddressSpec):
    """Return True only when the entire requested network/range is policy-covered."""
    return is_subset(requested, policy_addr)
