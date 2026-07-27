#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry


CMDB_OBJECTS = {
    "policies.json": ["firewall/policy"],
    "addresses.json": ["firewall/address", "firewall/addrgrp"],
    "services.json": ["firewall.service/custom", "firewall.service/group"],
    "interfaces.json": ["system/interface"],
}

STATIC_ROUTE_PATHS = ["router/static"]
MONITOR_ROUTE_PATHS = ["router/ipv4"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect FortiGate policy data through the REST API."
    )
    parser.add_argument("--host", default=os.getenv("FORTIGATE_HOST"), help="FortiGate host or IP")
    parser.add_argument("--token", default=os.getenv("FORTIGATE_TOKEN"), help="FortiGate API token")
    parser.add_argument("--vdom", default=os.getenv("FORTIGATE_VDOM", "root"), help="VDOM name")
    parser.add_argument(
        "--output-dir",
        default=os.getenv("FORTIGATE_OUTPUT_DIR", "data"),
        help="Directory where JSON files are written",
    )
    parser.add_argument(
        "--scheme",
        default=os.getenv("FORTIGATE_SCHEME", "https"),
        choices=("http", "https"),
        help="FortiGate API scheme",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=os.getenv("FORTIGATE_VERIFY_SSL", "").lower() in {"1", "true", "yes"},
        help="Verify FortiGate TLS certificate",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("FORTIGATE_TIMEOUT", "30")),
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--skip-monitor-routes",
        action="store_true",
        default=os.getenv("FORTIGATE_SKIP_MONITOR_ROUTES", "").lower() in {"1", "true", "yes"},
        help="Only collect configured static routes, not the runtime routing table.",
    )
    return parser.parse_args()


def build_session(token):
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
    )
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def fortigate_url(args, cmdb_path):
    host = args.host.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"{args.scheme}://{host}"
    return f"{host}/api/v2/cmdb/{cmdb_path}"


def fortigate_monitor_url(args, monitor_path):
    host = args.host.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"{args.scheme}://{host}"
    return f"{host}/api/v2/monitor/{monitor_path}"


def fetch_cmdb(session, args, cmdb_path):
    response = session.get(
        fortigate_url(args, cmdb_path),
        params={"vdom": args.vdom},
        timeout=args.timeout,
        verify=args.verify,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    if isinstance(results, dict):
        return list(results.values())
    return results


def _payload_results(payload):
    results = payload.get("results", [])
    if isinstance(results, dict):
        for key in ("routes", "route", "routing-table", "routing_table"):
            value = results.get(key)
            if isinstance(value, list):
                return value
        if all(isinstance(value, dict) for value in results.values()):
            return list(results.values())
        return [results]
    if isinstance(results, list):
        return results
    return []


def fetch_monitor(session, args, monitor_path):
    response = session.get(
        fortigate_monitor_url(args, monitor_path),
        params={"vdom": args.vdom},
        timeout=args.timeout,
        verify=args.verify,
    )
    response.raise_for_status()
    return _payload_results(response.json())


def object_names(values):
    names = []
    for value in values or []:
        if isinstance(value, dict) and value.get("name"):
            names.append(value["name"])
        elif isinstance(value, str):
            names.append(value)
    return names


def normalize_address(obj):
    out = dict(obj)
    if out.get("q_origin_key") and not out.get("name"):
        out["name"] = out["q_origin_key"]
    if out.get("member"):
        out["type"] = "group"
        out["group"] = object_names(out.get("member"))
    if out.get("type") == "iprange" and "iprange" not in out:
        start = out.get("start-ip")
        end = out.get("end-ip")
        if start and end:
            out["iprange"] = f"{start} {end}"
    return out


def normalize_service(obj):
    out = dict(obj)
    if out.get("q_origin_key") and not out.get("name"):
        out["name"] = out["q_origin_key"]
    if out.get("member"):
        out["group"] = object_names(out.get("member"))
    return out


def first_value(obj, keys):
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_route(obj, source):
    out = dict(obj)
    out["collected_from"] = source

    dst = first_value(
        out,
        (
            "dst",
            "network",
            "ip_mask",
            "ip-mask",
            "prefix",
            "destination",
            "dst-ip",
        ),
    )
    mask = first_value(out, ("mask", "netmask", "dst-mask"))
    if dst and mask and "/" not in str(dst) and " " not in str(dst):
        dst = f"{dst} {mask}"
    if dst:
        out["dst"] = str(dst)

    device = first_value(out, ("device", "interface", "ifname", "dev", "outgoing-interface"))
    if device:
        out["device"] = str(device)

    protocol = first_value(out, ("protocol", "proto", "type", "route-type"))
    if protocol:
        out["protocol"] = str(protocol).lower()

    if "status" not in out:
        out["status"] = "enable"

    return out


def route_key(route):
    return (
        route.get("dst") or route.get("network") or "",
        route.get("device") or route.get("interface") or "",
        route.get("gateway") or route.get("gw") or "",
        route.get("protocol") or route.get("type") or "",
    )


def collect_routes(session, args):
    routes = []
    for path in STATIC_ROUTE_PATHS:
        routes.extend(normalize_route(route, "cmdb/router/static") for route in fetch_cmdb(session, args, path))

    if not args.skip_monitor_routes:
        for path in MONITOR_ROUTE_PATHS:
            try:
                routes.extend(
                    normalize_route(route, f"monitor/{path}")
                    for route in fetch_monitor(session, args, path)
                )
            except requests.RequestException as exc:
                print(
                    f"Warning: could not collect monitor/{path}: {exc}",
                    file=sys.stderr,
                )

    deduped = {}
    for route in routes:
        deduped[route_key(route)] = route
    return list(deduped.values())


def normalize(filename, objects):
    if filename == "addresses.json":
        return [normalize_address(obj) for obj in objects if obj.get("name") or obj.get("q_origin_key")]
    if filename == "services.json":
        return [normalize_service(obj) for obj in objects if obj.get("name") or obj.get("q_origin_key")]
    return objects


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def main():
    args = parse_args()
    if not args.host or not args.token:
        print("FORTIGATE_HOST and FORTIGATE_TOKEN are required.", file=sys.stderr)
        return 2

    session = build_session(args.token)
    if not args.verify:
        disable_warnings(InsecureRequestWarning)
    output_dir = Path(args.output_dir)

    for filename, paths in CMDB_OBJECTS.items():
        objects = []
        for path in paths:
            objects.extend(fetch_cmdb(session, args, path))
        data = normalize(filename, objects)
        write_json(output_dir / filename, data)
        print(f"Wrote {len(data)} objects to {output_dir / filename}")

    routes = collect_routes(session, args)
    write_json(output_dir / "routes.json", routes)
    print(f"Wrote {len(routes)} objects to {output_dir / 'routes.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
