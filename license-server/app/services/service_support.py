from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packaging.version import InvalidVersion, Version
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.product_identity import PRODUCT_DISPLAY_NAME
from app.db.models import License
from app.db.models.enums import LicenseEventType, LicenseStatus
from app.repositories.event_repository import EventRepository
from app.repositories.admin_repository import AdminRepository
from app.services.idempotency_service import IdempotencyService, ServiceResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LicenseOperationSupport:
    def __init__(
        self,
        settings: Settings,
        idempotency: IdempotencyService,
        events: EventRepository,
    ) -> None:
        self.settings = settings
        self.idempotency = idempotency
        self.events = events

    def require_supported_client(self, app_version: str, minimum: str | None = None) -> None:
        required = minimum or self.settings.minimum_client_version
        try:
            current = Version(app_version)
            if current < Version(required):
                raise LicenseServiceError(
                    ErrorCode.CLIENT_VERSION_UNSUPPORTED,
                    f"{PRODUCT_DISPLAY_NAME} {required} or newer is required",
                )
        except InvalidVersion as exc:
            raise LicenseServiceError(ErrorCode.INVALID_REQUEST, "Invalid appVersion") from exc

    async def require_supported_client_policy(
        self, session: AsyncSession, app_version: str
    ) -> dict[str, Any] | None:
        policy = await AdminRepository().get_version_policy(session)
        minimum = policy.minimum_supported_version if policy else self.settings.minimum_client_version
        self.require_supported_client(app_version, minimum)
        try:
            current = Version(app_version)
            if policy and current < Version(policy.recommended_version):
                return {
                    "recommendedVersion": policy.recommended_version,
                    "downloadUrl": policy.download_url,
                    "releaseNotes": policy.release_notes,
                }
            return None
        except InvalidVersion as exc:
            raise LicenseServiceError(ErrorCode.INVALID_REQUEST, "Invalid appVersion") from exc

    def require_usable_license(self, license_record: License, now: datetime) -> None:
        if license_record.status == LicenseStatus.DISABLED:
            raise LicenseServiceError(
                ErrorCode.LICENSE_DISABLED, "License is disabled", license_id=license_record.id
            )
        if license_record.status == LicenseStatus.REVOKED:
            raise LicenseServiceError(
                ErrorCode.LICENSE_REVOKED, "License is revoked", license_id=license_record.id
            )
        if license_record.status == LicenseStatus.EXPIRED or (
            license_record.expires_at is not None and license_record.expires_at <= now
        ):
            license_record.status = LicenseStatus.EXPIRED
            raise LicenseServiceError(
                ErrorCode.LICENSE_EXPIRED, "License has expired", license_id=license_record.id
            )

    async def begin_idempotent(
        self,
        session: AsyncSession,
        *,
        endpoint: str,
        request_id: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> ServiceResult | None:
        return await self.idempotency.begin(
            session,
            endpoint=endpoint,
            request_id=request_id,
            payload=payload,
            now=now,
        )

    async def finish_success(
        self,
        session: AsyncSession,
        *,
        endpoint: str,
        request_id: str,
        body: dict[str, Any],
    ) -> ServiceResult:
        await self.idempotency.complete(
            session,
            endpoint=endpoint,
            request_id=request_id,
            status_code=200,
            body=body,
        )
        await session.commit()
        return ServiceResult(200, body)

    async def finish_error(
        self,
        session: AsyncSession,
        *,
        endpoint: str,
        request_id: str,
        trace_id: str,
        error: LicenseServiceError,
        event_type: LicenseEventType,
        now: datetime,
        ip: str | None,
        app_version: str | None,
        detail: dict[str, Any] | None = None,
    ) -> ServiceResult:
        body = error.response_body(trace_id)
        audit_event_type = {
            ErrorCode.LICENSE_DISABLED: LicenseEventType.LICENSE_DISABLED,
            ErrorCode.LICENSE_EXPIRED: LicenseEventType.LICENSE_EXPIRED,
            ErrorCode.TRIAL_EXPIRED: LicenseEventType.TRIAL_EXPIRED,
            ErrorCode.TRIAL_DISABLED: LicenseEventType.TRIAL_DISABLED,
        }.get(error.code, event_type)
        await self.events.add(
            session,
            event_type=audit_event_type,
            result=error.code.value,
            request_id=request_id,
            created_at=now,
            license_id=error.license_id,
            binding_id=error.binding_id,
            ip=ip,
            app_version=app_version,
            detail={**error.detail, **(detail or {})},
        )
        await self.idempotency.complete(
            session,
            endpoint=endpoint,
            request_id=request_id,
            status_code=error.status_code,
            body=body,
        )
        await session.commit()
        return ServiceResult(error.status_code, body)
