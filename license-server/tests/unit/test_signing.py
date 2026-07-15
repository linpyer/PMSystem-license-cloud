from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.core.signing import Ed25519Signer, SignedEnvelope, verify_envelope


def test_ed25519_envelope_round_trip() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "test-key")
    envelope = signer.sign({"schemaVersion": 1, "licenseId": "abc", "deviceId": "device"})
    decoded = verify_envelope(envelope, signer.public_key_base64url)
    assert decoded["licenseId"] == "abc"
    assert envelope.algorithm == "Ed25519"


def test_tampered_payload_fails_signature_verification() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "test-key")
    envelope = signer.sign({"licenseId": "original"})
    tampered = SignedEnvelope(
        payload=envelope.payload[:-1] + ("A" if envelope.payload[-1] != "A" else "B"),
        signature=envelope.signature,
        key_id=envelope.key_id,
    )
    with pytest.raises((InvalidSignature, ValueError)):
        verify_envelope(tampered, signer.public_key_base64url)


def test_different_keys_cannot_verify_signature() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "key-a")
    other = Ed25519Signer(Ed25519PrivateKey.generate(), "key-b")
    with pytest.raises(InvalidSignature):
        verify_envelope(signer.sign({"licenseId": "abc"}), other.public_key_base64url)

