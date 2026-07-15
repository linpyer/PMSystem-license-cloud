from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models.enums import LicenseType
from app.services.license_code_service import LicenseCodeService


class CapturingRepository:
    def __init__(self) -> None:
        self.record = None

    async def add_license(self, _session, record):
        self.record = record
        return record


@pytest.mark.parametrize(
    ("license_type", "valid_days"),
    [
        (LicenseType.MONTHLY, 30),
        (LicenseType.YEARLY, 365),
        (LicenseType.PERMANENT, None),
    ],
)
async def test_duration_license_rules(settings, license_type, valid_days) -> None:
    repository = CapturingRepository()
    created = await LicenseCodeService(settings, repository).create(
        object(), license_type=license_type
    )
    assert created.record.valid_days == valid_days
    assert created.record.expires_at is None
    assert created.plaintext_code not in created.record.license_code_hash


async def test_fixed_date_keeps_utc_expiration(settings) -> None:
    expiration = datetime(2027, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    created = await LicenseCodeService(settings, CapturingRepository()).create(
        object(), license_type=LicenseType.FIXED_DATE, expires_at=expiration
    )
    assert created.record.expires_at == expiration
    assert created.record.valid_days is None


async def test_fixed_date_requires_expiration(settings) -> None:
    with pytest.raises(ValueError):
        await LicenseCodeService(settings, CapturingRepository()).create(
            object(), license_type=LicenseType.FIXED_DATE
        )

