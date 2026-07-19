from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import generate_license_code, hash_license_code, mask_license_code
from app.db.models import License
from app.db.models.enums import LicenseStatus, LicenseType
from app.repositories.license_repository import LicenseRepository


@dataclass(frozen=True, slots=True)
class CreatedLicense:
    plaintext_code: str
    record: License


class LicenseCodeService:
    VALID_DAYS = {
        LicenseType.MONTHLY: 30,
        LicenseType.YEARLY: 365,
        LicenseType.PERMANENT: None,
        LicenseType.FIXED_DATE: None,
    }

    def __init__(self, settings: Settings, repository: LicenseRepository | None = None) -> None:
        self._settings = settings
        self._repository = repository or LicenseRepository()

    async def create(
        self,
        session: AsyncSession,
        *,
        license_type: LicenseType,
        expires_at: datetime | None = None,
        customer_name: str | None = None,
        customer_contact: str | None = None,
        remark: str | None = None,
    ) -> CreatedLicense:
        if license_type == LicenseType.TRIAL:
            raise ValueError("TRIAL licenses can only be issued by the device trial service")
        if license_type == LicenseType.FIXED_DATE:
            if expires_at is None:
                raise ValueError("fixed_date licenses require expires_at")
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must include a UTC offset")
            expires_at = expires_at.astimezone(timezone.utc)
        elif expires_at is not None:
            raise ValueError("expires_at is only valid for fixed_date licenses")

        plaintext = generate_license_code()
        record = License(
            license_code_hash=hash_license_code(plaintext, self._settings.code_pepper),
            license_code_masked=mask_license_code(plaintext),
            license_type=license_type,
            status=LicenseStatus.CREATED,
            valid_days=self.VALID_DAYS[license_type],
            activated_at=None,
            expires_at=expires_at,
            max_devices=1,
            customer_name=customer_name,
            customer_contact=customer_contact,
            remark=remark,
        )
        await self._repository.add_license(session, record)
        return CreatedLicense(plaintext, record)
