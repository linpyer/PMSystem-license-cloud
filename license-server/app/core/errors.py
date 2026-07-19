from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID


class ErrorCode(StrEnum):
    LICENSE_NOT_FOUND = "LICENSE_NOT_FOUND"
    LICENSE_ALREADY_BOUND = "LICENSE_ALREADY_BOUND"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"
    LICENSE_DISABLED = "LICENSE_DISABLED"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    DEVICE_DISABLED = "DEVICE_DISABLED"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    INVALID_REQUEST = "INVALID_REQUEST"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    CLIENT_VERSION_UNSUPPORTED = "CLIENT_VERSION_UNSUPPORTED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_TEMPORARILY_UNAVAILABLE = "SERVER_TEMPORARILY_UNAVAILABLE"
    TRIAL_EXPIRED = "TRIAL_EXPIRED"
    TRIAL_ALREADY_USED = "TRIAL_ALREADY_USED"
    TRIAL_CONVERTED = "TRIAL_CONVERTED"
    TRIAL_DISABLED = "TRIAL_DISABLED"
    TRIAL_DEVICE_MISMATCH = "TRIAL_DEVICE_MISMATCH"
    TRIAL_TEMPORARILY_UNAVAILABLE = "TRIAL_TEMPORARILY_UNAVAILABLE"
    ADMIN_AUTH_REQUIRED = "ADMIN_AUTH_REQUIRED"
    ADMIN_INVALID_CREDENTIALS = "ADMIN_INVALID_CREDENTIALS"
    ADMIN_TOTP_REQUIRED = "ADMIN_TOTP_REQUIRED"
    ADMIN_ACCOUNT_LOCKED = "ADMIN_ACCOUNT_LOCKED"
    ADMIN_FORBIDDEN = "ADMIN_FORBIDDEN"
    CSRF_FAILED = "CSRF_FAILED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"


ERROR_STATUS = {
    ErrorCode.LICENSE_NOT_FOUND: 404,
    ErrorCode.LICENSE_ALREADY_BOUND: 409,
    ErrorCode.LICENSE_EXPIRED: 403,
    ErrorCode.LICENSE_DISABLED: 403,
    ErrorCode.LICENSE_REVOKED: 403,
    ErrorCode.DEVICE_MISMATCH: 403,
    ErrorCode.DEVICE_DISABLED: 403,
    ErrorCode.INVALID_CREDENTIAL: 401,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.DUPLICATE_REQUEST: 409,
    ErrorCode.CLIENT_VERSION_UNSUPPORTED: 426,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SERVER_TEMPORARILY_UNAVAILABLE: 503,
    ErrorCode.TRIAL_EXPIRED: 403,
    ErrorCode.TRIAL_ALREADY_USED: 409,
    ErrorCode.TRIAL_CONVERTED: 409,
    ErrorCode.TRIAL_DISABLED: 403,
    ErrorCode.TRIAL_DEVICE_MISMATCH: 403,
    ErrorCode.TRIAL_TEMPORARILY_UNAVAILABLE: 503,
    ErrorCode.ADMIN_AUTH_REQUIRED: 401,
    ErrorCode.ADMIN_INVALID_CREDENTIALS: 401,
    ErrorCode.ADMIN_TOTP_REQUIRED: 401,
    ErrorCode.ADMIN_ACCOUNT_LOCKED: 429,
    ErrorCode.ADMIN_FORBIDDEN: 403,
    ErrorCode.CSRF_FAILED: 403,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.INVALID_STATE: 409,
}


class LicenseServiceError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        license_id: UUID | None = None,
        binding_id: UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = ERROR_STATUS[code]
        self.license_id = license_id
        self.binding_id = binding_id
        self.detail = detail or {}

    def response_body(self, trace_id: str) -> dict[str, Any]:
        return {
            "success": False,
            "traceId": trace_id,
            "error": {
                "code": self.code.value,
                "message": self.message,
                "retryable": self.retryable,
            },
        }
