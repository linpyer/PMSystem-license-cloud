from __future__ import annotations

import argparse
from pathlib import Path


FORBIDDEN_PATH_PARTS = {
    ".git",
    "build-input",
    "deploy",
    "license-admin",
    "license-server",
    "node_modules",
    "secrets",
    "tests",
}
FORBIDDEN_FILE_NAMES = {".env", ".env.production", "production_ed25519_private.pem"}
PRIVATE_KEY_SUFFIXES = {".key", ".pem"}
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".key",
    ".md",
    ".pem",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_CONTENT = (
    b"-----BEGIN PRIVATE KEY-----",
    b"LICENSE_ADMIN_SESSION_SECRET=",
    b"LICENSE_ADMIN_TOTP_ENCRYPTION_KEY=",
    b"POSTGRES_PASSWORD=",
    b"JWT_SECRET=",
)


def scan(roots: list[Path]) -> list[str]:
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            errors.append(f"release path does not exist: {root}")
            continue
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in files:
            relative_parts = {part.lower() for part in path.relative_to(root).parts}
            if relative_parts & FORBIDDEN_PATH_PARTS:
                errors.append(f"forbidden path in client release: {path}")
            lower_name = path.name.lower()
            if lower_name in FORBIDDEN_FILE_NAMES or (
                "private" in lower_name and path.suffix.lower() in PRIVATE_KEY_SUFFIXES
            ):
                errors.append(f"forbidden file in client release: {path}")
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                with path.open("rb") as stream:
                    overlap = b""
                    while chunk := stream.read(1024 * 1024):
                        content = overlap + chunk
                        for marker in FORBIDDEN_CONTENT:
                            if marker in content:
                                errors.append(f"forbidden secret marker in client release: {path}")
                                break
                        else:
                            overlap = content[-128:]
                            continue
                        break
            except OSError as exc:
                errors.append(f"unable to scan client release file {path}: {type(exc).__name__}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan DDREC client artifacts for server secrets")
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args()
    errors = scan(args.roots)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Client release security scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
