from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


EXPECTED_API_URL = "https://license.aixcc.top/api/v1"
EXPECTED_KEY_ID = "production-2026-01"


def validate(
    api_url: str,
    public_keys_path: Path,
    public_key_pem_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    parsed = urlparse(api_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        errors.append("production license API URL must use HTTPS and include a host")
    if api_url.rstrip("/") != EXPECTED_API_URL:
        errors.append(f"production license API URL must equal {EXPECTED_API_URL}")
    try:
        document = json.loads(public_keys_path.read_text(encoding="utf-8"))
        keys = document.get("keys", [])
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        return errors + [f"unable to read production public keys: {type(exc).__name__}"]
    if not isinstance(keys, list) or not keys:
        errors.append("production trusted public key set is empty")
        return errors
    if document.get("environment") != "production":
        errors.append("production trusted public key environment must be production")
    encoded_expected_key = ""
    for item in keys:
        key_id = str(item.get("keyId") or "") if isinstance(item, dict) else ""
        public_key = str(item.get("publicKey") or "") if isinstance(item, dict) else ""
        algorithm = str(item.get("algorithm") or "") if isinstance(item, dict) else ""
        if key_id != EXPECTED_KEY_ID:
            errors.append(f"production keyId must equal {EXPECTED_KEY_ID}")
        if algorithm != "Ed25519":
            errors.append(f"production key algorithm must be Ed25519 for keyId {key_id or '<empty>'}")
        try:
            decoded = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
        except (ValueError, TypeError):
            decoded = b""
        if "=" in public_key or len(decoded) != 32:
            errors.append(f"production public key material is invalid for keyId {key_id or '<empty>'}")
        if key_id == EXPECTED_KEY_ID:
            encoded_expected_key = public_key
    if public_key_pem_path is not None:
        try:
            pem = public_key_pem_path.read_bytes()
            if b"PRIVATE KEY" in pem:
                errors.append("production client public-key PEM contains private key material")
            loaded = serialization.load_pem_public_key(pem)
            if not isinstance(loaded, Ed25519PublicKey):
                errors.append("production client public-key PEM is not Ed25519")
            else:
                raw = loaded.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                encoded_pem = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
                if encoded_pem != encoded_expected_key:
                    errors.append("production public-key PEM does not match the trusted key registry")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"unable to read production public-key PEM: {type(exc).__name__}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DDREC production license trust config")
    parser.add_argument("--api-url", default=EXPECTED_API_URL)
    parser.add_argument(
        "--public-keys",
        type=Path,
        default=Path("app/assets/license/public_keys.production.json"),
    )
    parser.add_argument(
        "--public-key-pem",
        type=Path,
        default=Path("app/assets/license/production_ed25519_public.pem"),
    )
    args = parser.parse_args()
    errors = validate(args.api_url, args.public_keys, args.public_key_pem)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Production license API and public-key configuration are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
