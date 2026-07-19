from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def validate(api_url: str, public_keys_path: Path) -> list[str]:
    errors: list[str] = []
    parsed = urlparse(api_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        errors.append("production license API URL must use HTTPS and include a host")
    try:
        document = json.loads(public_keys_path.read_text(encoding="utf-8"))
        keys = document.get("keys", [])
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        return errors + [f"unable to read production public keys: {type(exc).__name__}"]
    if not isinstance(keys, list) or not keys:
        errors.append("production trusted public key set is empty")
        return errors
    for item in keys:
        key_id = str(item.get("keyId") or "") if isinstance(item, dict) else ""
        public_key = str(item.get("publicKey") or "") if isinstance(item, dict) else ""
        if not key_id or key_id.lower().startswith(("dev", "test", "staging")):
            errors.append("production keyId is missing or uses a non-production prefix")
        if len(public_key) < 40:
            errors.append(f"production public key material is invalid for keyId {key_id or '<empty>'}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PMSystem production license trust config")
    parser.add_argument("--api-url", required=True)
    parser.add_argument(
        "--public-keys",
        type=Path,
        default=Path("app/assets/license/public_keys.production.json"),
    )
    args = parser.parse_args()
    errors = validate(args.api_url, args.public_keys)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Production license API and public-key configuration are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
