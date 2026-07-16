from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken


_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_DUMMY_HASH = _PASSWORD_HASHER.hash("not-a-real-password-for-constant-work")


def validate_admin_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    checks = (
        any(char.islower() for char in password),
        any(char.isupper() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    )
    if not all(checks):
        raise ValueError("Password must include upper, lower, number, and symbol characters")


def hash_admin_password(password: str) -> str:
    validate_admin_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_admin_password(password: str, encoded: str | None) -> bool:
    target = encoded or _DUMMY_HASH
    try:
        return _PASSWORD_HASHER.verify(target, password) if encoded else False
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(encoded: str) -> bool:
    return _PASSWORD_HASHER.check_needs_rehash(encoded)


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_totp_secret(secret: str, encryption_key: str) -> str:
    return _fernet(encryption_key).encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_totp_secret(encrypted: str, encryption_key: str) -> str:
    try:
        return _fernet(encryption_key).decrypt(encrypted.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise ValueError("TOTP secret cannot be decrypted") from exc


def generate_totp_secret() -> str:
    return pyotp.random_base32(length=32)


def verify_totp(code: str, secret: str, *, now_timestamp: float) -> tuple[bool, int | None]:
    if len(code) != 6 or not code.isdigit():
        return False, None
    totp = pyotp.TOTP(secret)
    counter = int(now_timestamp // totp.interval)
    for delta in (-1, 0, 1):
        candidate = counter + delta
        if hmac.compare_digest(totp.at(candidate * totp.interval), code):
            return True, candidate
    return False, None


def generate_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def hash_admin_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def admin_token_matches(token: str, expected_hash: str, secret: str) -> bool:
    return hmac.compare_digest(hash_admin_token(token, secret), expected_hash)


def mask_username(username: str) -> str:
    normalized = username.strip().lower()
    if len(normalized) <= 2:
        return "*" * len(normalized)
    return normalized[0] + "*" * (len(normalized) - 2) + normalized[-1]


@dataclass(frozen=True, slots=True)
class SessionTokens:
    session: str
    csrf: str


def new_session_tokens() -> SessionTokens:
    return SessionTokens(generate_token(), generate_token())
