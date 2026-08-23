#!/usr/bin/env python3
"""Verify that an existing immutable release equals a verified extraction."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


MARKER = ".DDREC-ARCHIVE-SHA256"


def file_map(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != MARKER
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--archive-sha", required=True)
    args = parser.parse_args()

    marker = args.installed / MARKER
    if marker.exists() and marker.read_text(encoding="ascii").strip().lower() != args.archive_sha.lower():
        print("immutable release archive SHA256 mismatch", file=sys.stderr)
        return 40

    installed = file_map(args.installed)
    staging = file_map(args.staging)
    if installed.keys() != staging.keys():
        missing = sorted(staging.keys() - installed.keys())
        extra = sorted(installed.keys() - staging.keys())
        print(f"immutable release file set mismatch missing={missing} extra={extra}", file=sys.stderr)
        return 40

    for name in sorted(installed):
        if sha256(installed[name]) != sha256(staging[name]):
            print(f"immutable release content mismatch: {name}", file=sys.stderr)
            return 40

    mode = "archive-sha+content" if marker.exists() else "verified-content-legacy"
    print(f"immutableRelease=verified mode={mode} files={len(installed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
