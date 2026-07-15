from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    private_path = output_dir / "dev_ed25519_private.pem"
    public_path = output_dir / "dev_ed25519_public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("development key files already exist; remove them explicitly to rotate")

    private_key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(private_path, 0o600)
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local-only Ed25519 development keys")
    parser.add_argument("--output-dir", type=Path, default=Path(".secrets"))
    args = parser.parse_args()
    private_path, public_path = generate(args.output_dir)
    print("Development keys generated. Never use these keys in production.")
    print(f"Private key: {private_path.resolve()}")
    print(f"Public key:  {public_path.resolve()}")


if __name__ == "__main__":
    main()
