#!/usr/bin/env python3
"""Fingerprint sensitive archives/images and locate local duplicate copies.

This script identifies local copies only. Recipient attribution requires access,
sharing, registry, CI/CD, email, chat, object-storage, or endpoint audit logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path, help="Known archive/image files")
    parser.add_argument("--search-root", action="append", type=Path, default=[], help="Root to scan for duplicate files")
    parser.add_argument("--output", type=Path, default=Path("artifact-distribution-audit.json"))
    args = parser.parse_args()

    fingerprints = {}
    for artifact in args.artifacts:
        resolved = artifact.expanduser().resolve()
        if not resolved.is_file():
            parser.error(f"Artifact does not exist or is not a file: {artifact}")
        fingerprints[str(resolved)] = {"size": resolved.stat().st_size, "sha256": sha256(resolved)}

    target_hashes = {item["sha256"] for item in fingerprints.values()}
    matches = []
    for root in args.search_root:
        root = root.expanduser().resolve()
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            try:
                if candidate.is_file() and sha256(candidate) in target_hashes:
                    matches.append(str(candidate.resolve()))
            except (OSError, PermissionError):
                continue

    report = {
        "scope": "local filesystem fingerprints and exact duplicate discovery",
        "limitations": "Does not identify recipients without external audit logs.",
        "artifacts": fingerprints,
        "local_exact_matches": sorted(set(matches)),
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
