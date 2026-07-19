from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.licensing.constants import LicenseStatus
from app.licensing.models import LicensePayload


class LicensePolicy:
    ACTIVE_WINDOW = timedelta(hours=24)
    REQUIRED_VERIFY_WINDOW = timedelta(days=7)
    OFFLINE_GRACE_WINDOW = timedelta(days=21)
    CLOCK_ROLLBACK_TOLERANCE = timedelta(minutes=5)
    TRIAL_EXPIRING_WINDOW = timedelta(hours=72)

    def evaluate(
        self,
        payload: LicensePayload,
        *,
        now: datetime,
        last_seen_utc: datetime | None,
    ) -> LicenseStatus:
        now = now.astimezone(timezone.utc)
        if last_seen_utc is not None and now + self.CLOCK_ROLLBACK_TOLERANCE < last_seen_utc:
            return LicenseStatus.CLOCK_ROLLBACK_SUSPECTED
        if payload.license_type == "TRIAL":
            trial_expires_at = payload.trial_expires_at or payload.expires_at
            if payload.trial_started_at is None or trial_expires_at is None:
                return LicenseStatus.INVALID_LICENSE
            if now >= trial_expires_at:
                return LicenseStatus.TRIAL_EXPIRED
            if trial_expires_at - now <= self.TRIAL_EXPIRING_WINDOW:
                return LicenseStatus.TRIAL_EXPIRING
            return LicenseStatus.TRIAL_ACTIVE
        if payload.expires_at is not None and now >= payload.expires_at:
            return LicenseStatus.EXPIRED
        elapsed = max(timedelta(0), now - payload.last_verified_at)
        if elapsed <= self.ACTIVE_WINDOW:
            return LicenseStatus.ACTIVE
        if elapsed <= self.REQUIRED_VERIFY_WINDOW:
            return LicenseStatus.VERIFY_RECOMMENDED
        if elapsed <= self.OFFLINE_GRACE_WINDOW:
            return LicenseStatus.OFFLINE_GRACE
        return LicenseStatus.RESTRICTED
