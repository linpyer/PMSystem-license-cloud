from __future__ import annotations

import pyotp

from app.core.admin_security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    hash_admin_password,
    hash_admin_token,
    verify_admin_password,
    verify_totp,
)


def test_argon2id_password_hash_is_not_plaintext() -> None:
    encoded = hash_admin_password("StrongPassword!2026")
    assert encoded.startswith("$argon2id$")
    assert "StrongPassword!2026" not in encoded
    assert verify_admin_password("StrongPassword!2026", encoded)
    assert not verify_admin_password("wrong", encoded)


def test_totp_secret_is_encrypted_and_replay_counter_is_available() -> None:
    secret = pyotp.random_base32()
    encrypted = encrypt_totp_secret(secret, "test-encryption-key-long-enough")
    assert secret not in encrypted
    assert decrypt_totp_secret(encrypted, "test-encryption-key-long-enough") == secret
    timestamp = 1_800_000_000.0
    code = pyotp.TOTP(secret).at(timestamp)
    valid, counter = verify_totp(code, secret, now_timestamp=timestamp)
    assert valid and counter == int(timestamp // 30)


def test_session_token_hash_uses_server_secret() -> None:
    token = "one-time-session-token"
    digest = hash_admin_token(token, "server-side-secret")
    assert token not in digest
    assert len(digest) == 64
