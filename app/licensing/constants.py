from __future__ import annotations

import os
from enum import StrEnum


FINGERPRINT_VERSION = "win-v1"
LICENSE_PRODUCT = "PMSystem"
LICENSE_EDITION = "professional"
SUPPORTED_SCHEMA_VERSIONS = {1}


class LicenseStatus(StrEnum):
    TRIAL_PENDING = "TRIAL_PENDING"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    TRIAL_EXPIRING = "TRIAL_EXPIRING"
    TRIAL_EXPIRED = "TRIAL_EXPIRED"
    TRIAL_CONVERTED = "TRIAL_CONVERTED"
    UNLICENSED = "UNLICENSED"
    ACTIVE = "ACTIVE"
    VERIFY_RECOMMENDED = "VERIFY_RECOMMENDED"
    OFFLINE_GRACE = "OFFLINE_GRACE"
    RESTRICTED = "RESTRICTED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    INVALID_LICENSE = "INVALID_LICENSE"
    SERVER_UNAVAILABLE = "SERVER_UNAVAILABLE"
    CLOCK_ROLLBACK_SUSPECTED = "CLOCK_ROLLBACK_SUSPECTED"


class LicenseCapability(StrEnum):
    START_SHIPPING_RECORDING = "START_SHIPPING_RECORDING"
    START_RETURN_RECORDING = "START_RETURN_RECORDING"
    SAVE_NEW_RECORD = "SAVE_NEW_RECORD"
    CLOUD_UPLOAD = "CLOUD_UPLOAD"
    AUTO_SYNC = "AUTO_SYNC"
    VIEW_HISTORY = "VIEW_HISTORY"
    PLAY_VIDEO = "PLAY_VIDEO"
    QUERY = "QUERY"
    EXPORT = "EXPORT"
    SETTINGS = "SETTINGS"
    LICENSE_MANAGEMENT = "LICENSE_MANAGEMENT"


FULL_ACCESS_STATUSES = {
    LicenseStatus.TRIAL_ACTIVE,
    LicenseStatus.TRIAL_EXPIRING,
    LicenseStatus.ACTIVE,
    LicenseStatus.VERIFY_RECOMMENDED,
    LicenseStatus.OFFLINE_GRACE,
}

READ_ONLY_CAPABILITIES = {
    LicenseCapability.VIEW_HISTORY,
    LicenseCapability.PLAY_VIDEO,
    LicenseCapability.QUERY,
    LicenseCapability.EXPORT,
    LicenseCapability.SETTINGS,
    LicenseCapability.LICENSE_MANAGEMENT,
}


def license_api_base_url() -> str:
    return os.getenv("PMSYSTEM_LICENSE_API_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")


def license_environment() -> str:
    return os.getenv("PMSYSTEM_LICENSE_ENVIRONMENT", "development").strip().lower()


def trusted_public_keys_resource() -> str:
    environment = license_environment()
    filenames = {
        "development": "public_keys.json",
        "staging": "public_keys.staging.json",
        "production": "public_keys.production.json",
    }
    try:
        filename = filenames[environment]
    except KeyError as exc:
        raise ValueError(f"Unsupported license environment: {environment}") from exc
    return f"app/assets/license/{filename}"
