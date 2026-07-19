from __future__ import annotations

from datetime import timedelta

import pytest

from app.licensing.constants import LicenseCapability, LicenseStatus
from app.licensing.license_gate import LicenseGate
from app.licensing.license_policy import LicensePolicy
from tests.licensing.helpers import NOW, policy_payload
from dataclasses import replace


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(timedelta(0), LicenseStatus.ACTIVE), (timedelta(hours=24), LicenseStatus.ACTIVE),
     (timedelta(hours=24, seconds=1), LicenseStatus.VERIFY_RECOMMENDED),
     (timedelta(days=7), LicenseStatus.VERIFY_RECOMMENDED),
     (timedelta(days=7, seconds=1), LicenseStatus.OFFLINE_GRACE),
     (timedelta(days=21), LicenseStatus.OFFLINE_GRACE),
     (timedelta(days=21, seconds=1), LicenseStatus.RESTRICTED)],
)
def test_verification_age_policy(elapsed, expected):
    assert LicensePolicy().evaluate(
        policy_payload(verified_at=NOW - elapsed), now=NOW, last_seen_utc=NOW
    ) is expected


def test_expired_license_is_expired_even_when_recently_verified():
    assert LicensePolicy().evaluate(
        policy_payload(verified_at=NOW, expires_at=NOW), now=NOW, last_seen_utc=NOW
    ) is LicenseStatus.EXPIRED


def test_permanent_license_still_requires_periodic_verification():
    assert LicensePolicy().evaluate(
        policy_payload(verified_at=NOW - timedelta(days=22)), now=NOW, last_seen_utc=NOW
    ) is LicenseStatus.RESTRICTED


def test_clock_rollback_within_tolerance_is_allowed():
    result = LicensePolicy().evaluate(
        policy_payload(verified_at=NOW - timedelta(hours=1)),
        now=NOW, last_seen_utc=NOW + timedelta(minutes=5),
    )
    assert result is LicenseStatus.ACTIVE


def test_clock_rollback_beyond_tolerance_is_suspected():
    result = LicensePolicy().evaluate(
        policy_payload(verified_at=NOW - timedelta(hours=1)),
        now=NOW, last_seen_utc=NOW + timedelta(minutes=5, seconds=1),
    )
    assert result is LicenseStatus.CLOCK_ROLLBACK_SUSPECTED


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (timedelta(hours=168), LicenseStatus.TRIAL_ACTIVE),
        (timedelta(hours=72, seconds=1), LicenseStatus.TRIAL_ACTIVE),
        (timedelta(hours=72), LicenseStatus.TRIAL_EXPIRING),
        (timedelta(seconds=1), LicenseStatus.TRIAL_EXPIRING),
        (timedelta(0), LicenseStatus.TRIAL_EXPIRED),
    ],
)
def test_trial_uses_exact_signed_expiration_without_formal_grace(remaining, expected):
    payload = replace(
        policy_payload(),
        license_type="TRIAL",
        trial_started_at=NOW - timedelta(hours=96),
        trial_expires_at=NOW + remaining,
        expires_at=NOW + remaining,
    )
    assert LicensePolicy().evaluate(payload, now=NOW, last_seen_utc=NOW) is expected


@pytest.mark.parametrize("status", [LicenseStatus.ACTIVE, LicenseStatus.VERIFY_RECOMMENDED, LicenseStatus.OFFLINE_GRACE, LicenseStatus.TRIAL_ACTIVE, LicenseStatus.TRIAL_EXPIRING])
@pytest.mark.parametrize("capability", list(LicenseCapability))
def test_full_access_statuses_allow_every_capability(status, capability):
    assert LicenseGate(lambda: status).allows(capability)


@pytest.mark.parametrize("status", [LicenseStatus.TRIAL_PENDING, LicenseStatus.TRIAL_EXPIRED, LicenseStatus.TRIAL_CONVERTED, LicenseStatus.UNLICENSED, LicenseStatus.RESTRICTED, LicenseStatus.EXPIRED, LicenseStatus.DISABLED, LicenseStatus.REVOKED])
@pytest.mark.parametrize("capability", [LicenseCapability.START_SHIPPING_RECORDING, LicenseCapability.START_RETURN_RECORDING, LicenseCapability.SAVE_NEW_RECORD, LicenseCapability.CLOUD_UPLOAD, LicenseCapability.AUTO_SYNC])
def test_limited_statuses_reject_mutating_capabilities(status, capability):
    assert not LicenseGate(lambda: status).allows(capability)


@pytest.mark.parametrize("capability", [LicenseCapability.VIEW_HISTORY, LicenseCapability.PLAY_VIDEO, LicenseCapability.QUERY, LicenseCapability.EXPORT, LicenseCapability.SETTINGS, LicenseCapability.LICENSE_MANAGEMENT])
def test_restricted_mode_keeps_read_only_capabilities(capability):
    assert LicenseGate(lambda: LicenseStatus.RESTRICTED).allows(capability)
