from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import ErrorCode, LicenseServiceError
from app.db.models import License
from app.db.models.enums import LicenseStatus, LicenseType
from app.services.service_support import LicenseOperationSupport


class NoopIdempotency:
    pass


class NoopEvents:
    pass


def support(settings) -> LicenseOperationSupport:
    return LicenseOperationSupport(settings, NoopIdempotency(), NoopEvents())  # type: ignore[arg-type]


def license_record(status: LicenseStatus, expires_at=None) -> License:
    return License(
        license_code_hash="a" * 64,
        license_code_masked="PMS-****-****-****-ABCD",
        license_type=LicenseType.MONTHLY,
        status=status,
        valid_days=30,
        expires_at=expires_at,
        max_devices=1,
    )


def test_supported_client_version_is_accepted(settings) -> None:
    support(settings).require_supported_client("1.0.4")


@pytest.mark.parametrize(
    ("version", "code"),
    [
        ("1.0.3", ErrorCode.CLIENT_VERSION_UNSUPPORTED),
        ("not-a-version", ErrorCode.INVALID_REQUEST),
    ],
)
def test_invalid_client_versions_are_rejected(settings, version, code) -> None:
    with pytest.raises(LicenseServiceError) as captured:
        support(settings).require_supported_client(version)
    assert captured.value.code == code


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (LicenseStatus.DISABLED, ErrorCode.LICENSE_DISABLED),
        (LicenseStatus.REVOKED, ErrorCode.LICENSE_REVOKED),
    ],
)
def test_disabled_and_revoked_licenses_are_rejected(settings, status, code) -> None:
    with pytest.raises(LicenseServiceError) as captured:
        support(settings).require_usable_license(
            license_record(status), datetime.now(timezone.utc)
        )
    assert captured.value.code == code


def test_elapsed_expiration_marks_license_expired(settings) -> None:
    record = license_record(
        LicenseStatus.ACTIVE, datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    with pytest.raises(LicenseServiceError) as captured:
        support(settings).require_usable_license(record, datetime.now(timezone.utc))
    assert captured.value.code == ErrorCode.LICENSE_EXPIRED
    assert record.status == LicenseStatus.EXPIRED
