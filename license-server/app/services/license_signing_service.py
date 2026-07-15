from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.signing import Ed25519Signer, SignedEnvelope
from app.db.models import DeviceBinding, License
from app.repositories.signing_key_repository import SigningKeyRepository


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class LicenseSigningService:
    def __init__(
        self,
        settings: Settings,
        signer: Ed25519Signer,
        repository: SigningKeyRepository | None = None,
    ) -> None:
        self._settings = settings
        self._signer = signer
        self._repository = repository or SigningKeyRepository()

    async def issue(
        self,
        session: AsyncSession,
        *,
        license_record: License,
        binding: DeviceBinding,
        now: datetime,
    ) -> SignedEnvelope:
        await self._repository.ensure_active_key(
            session,
            key_id=self._signer.key_id,
            public_key=self._signer.public_key_base64url,
            now=now,
        )
        payload = {
            "schemaVersion": 1,
            "licenseId": str(license_record.id),
            "product": "PMSystem",
            "edition": "professional",
            "deviceId": binding.device_id,
            "fingerprintVersion": binding.fingerprint_version,
            "licenseType": license_record.license_type.value,
            "issuedAt": utc_iso(now),
            "expiresAt": utc_iso(license_record.expires_at),
            "lastVerifiedAt": utc_iso(binding.last_verified_at),
            "nextRequiredVerifyAt": utc_iso(
                binding.last_verified_at + timedelta(days=self._settings.required_verify_days)
            ),
            "graceUntil": utc_iso(
                binding.last_verified_at + timedelta(days=self._settings.offline_grace_days)
            ),
            "features": ["recording", "videoQuery", "statistics", "netdiskSync"],
            "keyId": self._signer.key_id,
            "nonce": secrets.token_urlsafe(18),
        }
        return self._signer.sign(payload)

