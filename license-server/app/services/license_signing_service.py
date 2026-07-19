from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.signing import Ed25519Signer, SignedEnvelope
from app.db.models import DeviceBinding, DeviceTrial, License
from app.db.models.enums import LicenseType
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
        trial: DeviceTrial | None = None,
    ) -> SignedEnvelope:
        await self._repository.ensure_active_key(
            session,
            key_id=self._signer.key_id,
            public_key=self._signer.public_key_base64url,
            now=now,
        )
        if license_record.license_type == LicenseType.TRIAL and trial is None:
            raise ValueError("Trial metadata is required when signing a trial license")
        next_required = binding.last_verified_at + timedelta(days=self._settings.required_verify_days)
        grace_until = binding.last_verified_at + timedelta(
            days=self._settings.required_verify_days + self._settings.offline_grace_days
        )
        if trial is not None:
            next_required = min(next_required, trial.expires_at)
            grace_until = trial.expires_at
        payload = {
            "schemaVersion": 1,
            "licenseId": str(license_record.id),
            "product": "PMSystem",
            "edition": "professional",
            "deviceId": binding.device_id,
            "fingerprintVersion": binding.fingerprint_version,
            "licenseType": license_record.license_type.value,
            "issuedAt": utc_iso(now),
            "activatedAt": utc_iso(license_record.activated_at),
            "expiresAt": utc_iso(license_record.expires_at),
            "lastVerifiedAt": utc_iso(binding.last_verified_at),
            "nextRequiredVerifyAt": utc_iso(next_required),
            "graceUntil": utc_iso(grace_until),
            "features": ["recording", "videoQuery", "statistics", "netdiskSync"],
            "keyId": self._signer.key_id,
            "nonce": secrets.token_urlsafe(18),
        }
        if trial is not None:
            payload["trialStartedAt"] = utc_iso(trial.started_at)
            payload["trialExpiresAt"] = utc_iso(trial.expires_at)
        return self._signer.sign(payload)
