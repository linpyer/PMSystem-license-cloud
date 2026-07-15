from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.licensing.errors import LicenseValidationError


def parse_utc(value: object, *, field: str, optional: bool = False) -> datetime | None:
    if value in (None, ""):
        if optional:
            return None
        raise LicenseValidationError(f"{field} is required")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LicenseValidationError(f"{field} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise LicenseValidationError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SignedLicense:
    payload: str
    signature: str
    key_id: str
    algorithm: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SignedLicense":
        return cls(
            payload=str(value.get("payload") or ""),
            signature=str(value.get("signature") or ""),
            key_id=str(value.get("keyId") or ""),
            algorithm=str(value.get("algorithm") or ""),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "payload": self.payload,
            "signature": self.signature,
            "keyId": self.key_id,
            "algorithm": self.algorithm,
        }


@dataclass(frozen=True, slots=True)
class LicensePayload:
    schema_version: int
    license_id: str
    product: str
    edition: str
    device_id: str
    fingerprint_version: str
    license_type: str
    issued_at: datetime
    expires_at: datetime | None
    last_verified_at: datetime
    next_required_verify_at: datetime
    grace_until: datetime
    features: tuple[str, ...]
    key_id: str
    nonce: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "LicensePayload":
        try:
            schema_version = int(value.get("schemaVersion"))
        except (TypeError, ValueError) as exc:
            raise LicenseValidationError("schemaVersion is invalid") from exc
        features = value.get("features")
        if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
            raise LicenseValidationError("features must be a string list")
        return cls(
            schema_version=schema_version,
            license_id=str(value.get("licenseId") or ""),
            product=str(value.get("product") or ""),
            edition=str(value.get("edition") or ""),
            device_id=str(value.get("deviceId") or ""),
            fingerprint_version=str(value.get("fingerprintVersion") or ""),
            license_type=str(value.get("licenseType") or ""),
            issued_at=parse_utc(value.get("issuedAt"), field="issuedAt"),  # type: ignore[arg-type]
            expires_at=parse_utc(value.get("expiresAt"), field="expiresAt", optional=True),
            last_verified_at=parse_utc(value.get("lastVerifiedAt"), field="lastVerifiedAt"),  # type: ignore[arg-type]
            next_required_verify_at=parse_utc(
                value.get("nextRequiredVerifyAt"), field="nextRequiredVerifyAt"
            ),  # type: ignore[arg-type]
            grace_until=parse_utc(value.get("graceUntil"), field="graceUntil"),  # type: ignore[arg-type]
            features=tuple(features),
            key_id=str(value.get("keyId") or ""),
            nonce=str(value.get("nonce") or ""),
        )


@dataclass(slots=True)
class LocalLicenseRecord:
    schema_version: int
    license_id: str
    device_id: str
    fingerprint_version: str
    signed_license: SignedLicense
    credential: str
    saved_at: datetime
    last_seen_utc: datetime
    remote_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "licenseId": self.license_id,
            "deviceId": self.device_id,
            "fingerprintVersion": self.fingerprint_version,
            **self.signed_license.as_dict(),
            "credential": self.credential,
            "savedAt": utc_iso(self.saved_at),
            "lastSeenUtc": utc_iso(self.last_seen_utc),
            "remoteStatus": self.remote_status,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "LocalLicenseRecord":
        envelope = SignedLicense.from_mapping(value)
        return cls(
            schema_version=int(value.get("schemaVersion") or 1),
            license_id=str(value.get("licenseId") or ""),
            device_id=str(value.get("deviceId") or ""),
            fingerprint_version=str(value.get("fingerprintVersion") or ""),
            signed_license=envelope,
            credential=str(value.get("credential") or ""),
            saved_at=parse_utc(value.get("savedAt"), field="savedAt"),  # type: ignore[arg-type]
            last_seen_utc=parse_utc(value.get("lastSeenUtc"), field="lastSeenUtc"),  # type: ignore[arg-type]
            remote_status=str(value.get("remoteStatus") or ""),
        )
