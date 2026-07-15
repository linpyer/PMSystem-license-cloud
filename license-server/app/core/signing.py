from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.security import base64url_decode, base64url_encode, canonical_json_bytes


@dataclass(frozen=True, slots=True)
class SignedEnvelope:
    payload: str
    signature: str
    key_id: str
    algorithm: str = "Ed25519"

    def as_dict(self) -> dict[str, str]:
        return {
            "payload": self.payload,
            "signature": self.signature,
            "keyId": self.key_id,
            "algorithm": self.algorithm,
        }


class Ed25519Signer:
    def __init__(self, private_key: Ed25519PrivateKey, key_id: str) -> None:
        self._private_key = private_key
        self.key_id = key_id

    @classmethod
    def from_pem_file(cls, path: Path, key_id: str) -> "Ed25519Signer":
        raw = path.read_bytes()
        private_key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("configured signing key is not an Ed25519 private key")
        return cls(private_key, key_id)

    @property
    def public_key_base64url(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64url_encode(raw)

    def sign(self, payload: dict[str, Any]) -> SignedEnvelope:
        canonical = canonical_json_bytes(payload)
        return SignedEnvelope(
            payload=base64url_encode(canonical),
            signature=base64url_encode(self._private_key.sign(canonical)),
            key_id=self.key_id,
        )


def verify_envelope(envelope: SignedEnvelope, public_key_base64url: str) -> dict[str, Any]:
    import json

    public_key = Ed25519PublicKey.from_public_bytes(base64url_decode(public_key_base64url))
    payload = base64url_decode(envelope.payload)
    public_key.verify(base64url_decode(envelope.signature), payload)
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("signed payload must be a JSON object")
    return decoded

