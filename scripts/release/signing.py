from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


SIGNED_FIELDS = (
    "product", "version", "buildNumber", "edition", "environment",
    "architecture", "channel", "fileName", "fileSize", "sha256", "publishedAt",
)


def canonical_bytes(document: dict) -> bytes:
    missing = [field for field in SIGNED_FIELDS if field not in document]
    if missing:
        raise ValueError(f"manifest missing fields: {', '.join(missing)}")
    normalized = {field: document[field] for field in SIGNED_FIELDS}
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def decode_signature(value: str) -> bytes:
    padded = value.strip().replace("-", "+").replace("_", "/")
    padded += "=" * ((4 - len(padded) % 4) % 4)
    return base64.b64decode(padded, validate=True)


def sign(manifest: Path, private_key: Path) -> str:
    document = json.loads(manifest.read_text(encoding="utf-8-sig"))
    key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key is not Ed25519")
    signature = key.sign(canonical_bytes(document))
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def verify(manifest: Path, signature: str, public_key: Path) -> None:
    document = json.loads(manifest.read_text(encoding="utf-8-sig"))
    key = serialization.load_pem_public_key(public_key.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key is not Ed25519")
    key.verify(decode_signature(signature), canonical_bytes(document))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign and verify iVRec update manifests")
    commands = parser.add_subparsers(dest="command", required=True)
    sign_parser = commands.add_parser("sign")
    sign_parser.add_argument("--manifest", required=True, type=Path)
    sign_parser.add_argument("--private-key", required=True, type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--manifest", required=True, type=Path)
    verify_parser.add_argument("--signature", required=True)
    verify_parser.add_argument("--public-key", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "sign":
            print(sign(args.manifest, args.private_key))
        else:
            verify(args.manifest, args.signature, args.public_key)
            print("signature valid")
        return 0
    except (OSError, ValueError, InvalidSignature, json.JSONDecodeError) as exc:
        print(f"signature operation failed: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
