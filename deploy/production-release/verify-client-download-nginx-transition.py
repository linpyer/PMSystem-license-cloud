#!/usr/bin/env python3
"""Allow only the audited DDREC-history + iVRec-current download transition."""

import argparse
import importlib.util
import sys
from pathlib import Path


EXIT_PREFLIGHT = 10
EXIT_CHANGED = 40
LEGACY_LOCATION = (
    "^/releases/stable/(standard|license)/[0-9]+\\.[0-9]+\\.[0-9]+"
    "(?:/[1-9][0-9]*)?/DDREC-[0-9]+\\.[0-9]+\\.[0-9]+"
    "-(standard|license)-Setup\\.exe$"
)
CURRENT_LOCATION = (
    "^/releases/stable/(standard|license)/[0-9]+\\.[0-9]+\\.[0-9]+"
    "(?:/[1-9][0-9]*)?/(?:DDREC|iVRec)-[0-9]+\\.[0-9]+\\.[0-9]+"
    "-(standard|license)-Setup\\.exe$"
)


def load_tokenizer(script_dir: Path):
    path = script_dir / "audit-nginx-config.py"
    spec = importlib.util.spec_from_file_location("ddrec_nginx_auditor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Nginx auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.tokenize


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    args = parser.parse_args()

    for label, path in (("active", args.active), ("expected", args.expected)):
        if not path.is_file():
            print(f"ERROR: {label} download Nginx config is missing: {path}", file=sys.stderr)
            return EXIT_PREFLIGHT

    try:
        tokenize = load_tokenizer(Path(__file__).resolve().parent)
        active = tokenize(args.active.read_text(encoding="utf-8-sig"))
        expected = tokenize(args.expected.read_text(encoding="utf-8-sig"))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: could not audit client download Nginx transition: {exc}", file=sys.stderr)
        return EXIT_PREFLIGHT

    if expected.count(CURRENT_LOCATION) != 1 or LEGACY_LOCATION in expected:
        print("ERROR: expected config does not contain exactly one approved current read rule", file=sys.stderr)
        return EXIT_PREFLIGHT

    if active == expected:
        print("CLIENT_DOWNLOAD_NGINX_TRANSITION=ALREADY_CURRENT")
        return 0

    if active.count(LEGACY_LOCATION) != 1 or CURRENT_LOCATION in active:
        print("ERROR: active config is not the approved historical DDREC-only baseline", file=sys.stderr)
        return EXIT_CHANGED

    transitioned = [CURRENT_LOCATION if token == LEGACY_LOCATION else token for token in active]
    if transitioned != expected:
        print("ERROR: Nginx change contains semantics beyond the approved read-rule transition", file=sys.stderr)
        return EXIT_CHANGED

    print("CLIENT_DOWNLOAD_NGINX_TRANSITION=APPROVED_DDREC_HISTORY_PLUS_IVREC_CURRENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
