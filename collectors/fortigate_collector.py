#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import logging
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

MANIFEST_FILE = "manifest.json"
POINTER_FILE = "current.json"
SNAPSHOTS_DIR = "snapshots"
REQUIRED_DATA_FILES = (
    "policies.json",
    "addresses.json",
    "services.json",
    "routes.json",
    "interfaces.json",
)


logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger=logging.getLogger(__name__)

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
    parser.add_argument(
        "--keep-snapshots",
        type=int,
        default=int(os.getenv("FORTIGATE_KEEP_SNAPSHOTS", "10")),
        help="Number of completed snapshots to retain (default: 10).",
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
                logger.warning("Could not collect monitor route", extra={"monitor_path":path}, exc_info=exc)

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


def _json_bytes(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_bytes_durable(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def _safe_source_host(args):
    host = args.host.rstrip("/")
    parsed = urlsplit(host if "://" in host else f"{args.scheme}://{host}")
    return parsed.hostname or host


def _snapshot_id():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


@contextmanager
def collector_lock(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".collector.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another FortiGate collection is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def collect_dataset(session, args):
    dataset = {}
    for filename, paths in CMDB_OBJECTS.items():
        objects = []
        for path in paths:
            objects.extend(fetch_cmdb(session, args, path))
        dataset[filename] = normalize(filename, objects)

    dataset["routes.json"] = collect_routes(session, args)
    missing = [filename for filename in REQUIRED_DATA_FILES if filename not in dataset]
    if missing:
        raise RuntimeError(f"Collection did not produce required files: {', '.join(missing)}")
    for filename, records in dataset.items():
        if not isinstance(records, list):
            raise RuntimeError(f"Collected dataset is not a list: {filename}")
    return dataset


def publish_snapshot(output_dir, dataset, args):
    snapshots_dir = output_dir / SNAPSHOTS_DIR
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = _snapshot_id()
    staging_dir = snapshots_dir / f".staging-{snapshot_id}"
    final_dir = snapshots_dir / snapshot_id
    staging_dir.mkdir(mode=0o750)

    try:
        files = {}
        for filename in REQUIRED_DATA_FILES:
            payload = _json_bytes(dataset[filename])
            _write_bytes_durable(staging_dir / filename, payload)
            files[filename] = {
                "sha256": _sha256(payload),
                "bytes": len(payload),
                "records": len(dataset[filename]),
            }

        collected_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "collected_at": collected_at,
            "source": {
                "host": _safe_source_host(args),
                "vdom": args.vdom,
                "scheme": args.scheme,
                "tls_verified": bool(args.verify),
                "monitor_routes_included": not args.skip_monitor_routes,
            },
            "files": files,
        }
        manifest_payload = _json_bytes(manifest)
        _write_bytes_durable(staging_dir / MANIFEST_FILE, manifest_payload)
        _fsync_directory(staging_dir)

        os.rename(staging_dir, final_dir)
        _fsync_directory(snapshots_dir)

        pointer = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "path": f"{SNAPSHOTS_DIR}/{snapshot_id}",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        pointer_tmp = output_dir / f".{POINTER_FILE}.{uuid.uuid4().hex}.tmp"
        _write_bytes_durable(pointer_tmp, _json_bytes(pointer))
        os.replace(pointer_tmp, output_dir / POINTER_FILE)
        _fsync_directory(output_dir)
        return snapshot_id, final_dir, manifest
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def prune_snapshots(output_dir, active_snapshot_id, keep):
    if keep < 1:
        raise ValueError("--keep-snapshots must be at least 1")
    snapshots_dir = output_dir / SNAPSHOTS_DIR
    completed = sorted(
        (path for path in snapshots_dir.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: path.name,
        reverse=True,
    )
    retained = {path.name for path in completed[:keep]}
    retained.add(active_snapshot_id)
    for path in completed:
        if path.name not in retained:
            shutil.rmtree(path)
            logger.info("Old FortiGate snapshot removed", extra={"snapshot_id": path.name})


def main():
    args = parse_args()
    if not args.host or not args.token:
        logger.error("FORTIGATE_HOST and FORTIGATE_TOKEN are required")
        return 2
    if args.keep_snapshots < 1:
        logger.error("FORTIGATE_KEEP_SNAPSHOTS must be at least 1")
        return 2

    session = build_session(args.token)
    if not args.verify:
        disable_warnings(InsecureRequestWarning)
    output_dir = Path(args.output_dir)

    try:
        with collector_lock(output_dir):
            dataset = collect_dataset(session, args)
            snapshot_id, snapshot_dir, manifest = publish_snapshot(output_dir, dataset, args)
            prune_snapshots(output_dir, snapshot_id, args.keep_snapshots)
    except Exception:
        logger.exception("FortiGate snapshot collection failed")
        return 1

    logger.info(
        "FortiGate snapshot published",
        extra={
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snapshot_dir),
            "record_counts": {name: entry["records"] for name, entry in manifest["files"].items()},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
