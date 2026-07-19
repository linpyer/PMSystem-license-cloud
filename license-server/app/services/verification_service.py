from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import credential_matches, device_id_prefix
from app.db.models.enums import (
    BindingStatus,
    DeviceTrialStatus,
    LicenseEventType,
    LicenseStatus,
    LicenseType,
)
from app.repositories.event_repository import EventRepository
from app.repositories.license_repository import LicenseRepository
from app.repositories.trial_repository import TrialRepository
from app.schemas.licenses import RefreshRequest, VerifyRequest
from app.services.idempotency_service import IdempotencyService, ServiceResult
from app.services.license_signing_service import LicenseSigningService
from app.services.service_support import LicenseOperationSupport, utc_now


class VerificationService(LicenseOperationSupport):
    def __init__(
        self,
        settings: Settings,
        signing: LicenseSigningService,
        *,
        licenses: LicenseRepository | None = None,
        events: EventRepository | None = None,
        idempotency: IdempotencyService,
        trials: TrialRepository | None = None,
    ) -> None:
        event_repository = events or EventRepository()
        super().__init__(settings, idempotency, event_repository)
        self.licenses = licenses or LicenseRepository()
        self.signing = signing
        self.trials = trials or TrialRepository()

    async def verify(
        self,
        session: AsyncSession,
        request: VerifyRequest,
        *,
        trace_id: str,
        ip: str | None,
    ) -> ServiceResult:
        return await self._issue(
            session,
            request,
            endpoint="/api/v1/licenses/verify",
            success_event=LicenseEventType.VERIFIED,
            failure_event=LicenseEventType.VERIFICATION_FAILED,
            trace_id=trace_id,
            ip=ip,
            update_verification_time=True,
        )

    async def refresh(
        self,
        session: AsyncSession,
        request: RefreshRequest,
        *,
        trace_id: str,
        ip: str | None,
    ) -> ServiceResult:
        return await self._issue(
            session,
            request,
            endpoint="/api/v1/licenses/refresh",
            success_event=LicenseEventType.REFRESHED,
            failure_event=LicenseEventType.REFRESH_FAILED,
            trace_id=trace_id,
            ip=ip,
            update_verification_time=False,
        )

    async def _issue(
        self,
        session: AsyncSession,
        request: VerifyRequest | RefreshRequest,
        *,
        endpoint: str,
        success_event: LicenseEventType,
        failure_event: LicenseEventType,
        trace_id: str,
        ip: str | None,
        update_verification_time: bool,
    ) -> ServiceResult:
        now = utc_now()
        payload = request.model_dump(mode="json", by_alias=True)
        replay = await self.begin_idempotent(
            session,
            endpoint=endpoint,
            request_id=request.request_id,
            payload=payload,
            now=now,
        )
        if replay is not None:
            return replay

        try:
            update_advisory = await self.require_supported_client_policy(session, request.app_version)
            license_record = await self.licenses.get_by_id_for_update(session, request.license_id)
            if license_record is None:
                raise LicenseServiceError(ErrorCode.LICENSE_NOT_FOUND, "License was not found")
            trial = None
            if license_record.license_type == LicenseType.TRIAL:
                trial = await self.trials.get_for_license(session, license_record.id, lock=True)
                if trial is None or trial.device_id != request.device_id:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_DEVICE_MISMATCH,
                        "Trial device does not match",
                        license_id=license_record.id,
                    )
                if trial.status == DeviceTrialStatus.CONVERTED:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_CONVERTED,
                        "This trial was converted to a formal license",
                        license_id=license_record.id,
                    )
                if trial.status == DeviceTrialStatus.DISABLED:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_DISABLED,
                        "This trial is disabled",
                        license_id=license_record.id,
                    )
                if trial.status == DeviceTrialStatus.EXPIRED or now >= trial.expires_at:
                    trial.status = DeviceTrialStatus.EXPIRED
                    license_record.status = LicenseStatus.EXPIRED
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_EXPIRED,
                        "The seven-day trial has expired",
                        license_id=license_record.id,
                    )
            else:
                self.require_usable_license(license_record, now)
            binding = await self.licenses.get_active_binding_for_update(session, license_record.id)
            if binding is None:
                latest = await self.licenses.get_latest_binding_for_device(
                    session, license_record.id, request.device_id
                )
                if latest is not None and latest.status == BindingStatus.DISABLED:
                    raise LicenseServiceError(
                        ErrorCode.DEVICE_DISABLED,
                        "Device binding is disabled",
                        license_id=license_record.id,
                        binding_id=latest.id,
                    )
                raise LicenseServiceError(
                    ErrorCode.DEVICE_MISMATCH,
                    "No active binding exists for this device",
                    license_id=license_record.id,
                )
            if binding.device_id != request.device_id:
                raise LicenseServiceError(
                    ErrorCode.DEVICE_MISMATCH,
                    "Device does not match the active binding",
                    license_id=license_record.id,
                    binding_id=binding.id,
                )
            if not credential_matches(
                request.credential,
                binding.device_credential_hash,
                self.settings.device_credential_pepper,
            ):
                raise LicenseServiceError(
                    ErrorCode.INVALID_CREDENTIAL,
                    "Device credential is invalid",
                    license_id=license_record.id,
                    binding_id=binding.id,
                )

            if update_verification_time:
                binding.last_verified_at = now
            binding.last_ip = ip
            binding.app_version = request.app_version
            if trial is not None:
                trial.last_seen_at = now
                trial.last_ip = ip
                trial.app_version = request.app_version
            envelope = await self.signing.issue(
                session, license_record=license_record, binding=binding, trial=trial, now=now
            )
            await self.events.add(
                session,
                event_type=(LicenseEventType.TRIAL_VERIFIED if trial is not None else success_event),
                result="SUCCESS",
                request_id=request.request_id,
                created_at=now,
                license_id=license_record.id,
                binding_id=binding.id,
                ip=ip,
                app_version=request.app_version,
                detail={"deviceIdPrefix": device_id_prefix(request.device_id)},
            )
            body = {"success": True, "traceId": trace_id, "license": envelope.as_dict()}
            if update_advisory:
                body["update"] = update_advisory
            return await self.finish_success(
                session, endpoint=endpoint, request_id=request.request_id, body=body
            )
        except LicenseServiceError as error:
            return await self.finish_error(
                session,
                endpoint=endpoint,
                request_id=request.request_id,
                trace_id=trace_id,
                error=error,
                event_type=(
                    LicenseEventType.TRIAL_EXPIRED
                    if error.code == ErrorCode.TRIAL_EXPIRED
                    else failure_event
                ),
                now=now,
                ip=ip,
                app_version=request.app_version,
                detail={"deviceIdPrefix": device_id_prefix(request.device_id)},
            )
