from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import device_id_prefix, generate_device_credential, hash_device_credential
from app.db.models import DeviceBinding, DeviceTrial, License
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
from app.schemas.licenses import TrialActivateRequest
from app.services.idempotency_service import IdempotencyService, ServiceResult
from app.services.license_signing_service import LicenseSigningService
from app.services.service_support import LicenseOperationSupport, utc_now


TRIAL_DURATION = timedelta(hours=168)


class TrialActivationService(LicenseOperationSupport):
    ENDPOINT = "/api/v1/trials/activate"

    def __init__(
        self,
        settings: Settings,
        signing: LicenseSigningService,
        *,
        licenses: LicenseRepository | None = None,
        trials: TrialRepository | None = None,
        events: EventRepository | None = None,
        idempotency: IdempotencyService,
    ) -> None:
        event_repository = events or EventRepository()
        super().__init__(settings, idempotency, event_repository)
        self.licenses = licenses or LicenseRepository()
        self.trials = trials or TrialRepository()
        self.signing = signing

    async def activate(
        self,
        session: AsyncSession,
        request: TrialActivateRequest,
        *,
        trace_id: str,
        ip: str | None,
    ) -> ServiceResult:
        now = utc_now()
        payload = request.model_dump(mode="json", by_alias=True)
        replay = await self.begin_idempotent(
            session, endpoint=self.ENDPOINT, request_id=request.request_id, payload=payload, now=now
        )
        if replay is not None:
            return replay

        try:
            update_advisory = await self.require_supported_client_policy(session, request.app_version)
            await self.trials.lock_device(session, request.device_id, request.fingerprint_version)
            trial = await self.trials.get_for_device(
                session, request.device_id, request.fingerprint_version, lock=True
            )
            deleted_trial = None
            if trial is None:
                deleted_trial = await self.trials.get_latest_deleted_for_device(
                    session, request.device_id, request.fingerprint_version
                )
            credential = generate_device_credential()
            credential_hash = hash_device_credential(
                credential, self.settings.device_credential_pepper
            )
            if trial is None:
                expires_at = now + TRIAL_DURATION
                license_record = License(
                    license_code_hash=None,
                    license_code_masked=None,
                    license_type=LicenseType.TRIAL,
                    status=LicenseStatus.ACTIVE,
                    valid_days=7,
                    activated_at=now,
                    expires_at=expires_at,
                    max_devices=1,
                    remark="Server-issued seven-day device trial",
                )
                await self.licenses.add_license(session, license_record)
                binding = DeviceBinding(
                    license_id=license_record.id,
                    device_id=request.device_id,
                    fingerprint_version=request.fingerprint_version,
                    device_name=request.device_name,
                    os_version=request.os_version,
                    app_version=request.app_version,
                    status=BindingStatus.ACTIVE,
                    first_activated_at=now,
                    last_verified_at=now,
                    last_ip=ip,
                    device_credential_hash=credential_hash,
                )
                await self.licenses.add_binding(session, binding)
                trial = DeviceTrial(
                    device_id=request.device_id,
                    fingerprint_version=request.fingerprint_version,
                    trial_license_id=license_record.id,
                    status=DeviceTrialStatus.ACTIVE,
                    started_at=now,
                    expires_at=expires_at,
                    first_ip=ip,
                    last_ip=ip,
                    last_seen_at=now,
                    device_name=request.device_name,
                    os_version=request.os_version,
                    app_version=request.app_version,
                )
                await self.trials.add(session, trial)
                event_type = (
                    LicenseEventType.TRIAL_REACTIVATED_AFTER_DELETE
                    if deleted_trial is not None
                    else LicenseEventType.TRIAL_ACTIVATED
                )
            else:
                if trial.status == DeviceTrialStatus.CONVERTED:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_CONVERTED,
                        "This device trial was converted to a formal license",
                        license_id=trial.trial_license_id,
                    )
                if trial.status == DeviceTrialStatus.DISABLED:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_DISABLED,
                        "This device trial is disabled",
                        license_id=trial.trial_license_id,
                    )
                if trial.status == DeviceTrialStatus.EXPIRED or now >= trial.expires_at:
                    trial.status = DeviceTrialStatus.EXPIRED
                    license_record = await self.licenses.get_by_id_for_update(
                        session, trial.trial_license_id
                    )
                    if license_record is not None:
                        license_record.status = LicenseStatus.EXPIRED
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_EXPIRED,
                        "The seven-day trial has expired",
                        license_id=trial.trial_license_id,
                    )
                license_record = await self.licenses.get_by_id_for_update(
                    session, trial.trial_license_id
                )
                if license_record is None:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_TEMPORARILY_UNAVAILABLE,
                        "Trial license state is temporarily unavailable",
                        retryable=True,
                    )
                binding = await self.licenses.get_active_binding_for_update(
                    session, license_record.id
                )
                if binding is None or binding.device_id != request.device_id:
                    raise LicenseServiceError(
                        ErrorCode.TRIAL_DEVICE_MISMATCH,
                        "Trial device binding does not match",
                        license_id=license_record.id,
                    )
                binding.device_credential_hash = credential_hash
                binding.last_verified_at = now
                binding.last_ip = ip
                binding.app_version = request.app_version
                binding.device_name = request.device_name
                binding.os_version = request.os_version
                trial.last_seen_at = now
                trial.last_ip = ip
                trial.app_version = request.app_version
                trial.device_name = request.device_name
                trial.os_version = request.os_version
                event_type = LicenseEventType.TRIAL_REACTIVATED_SAME_DEVICE

            envelope = await self.signing.issue(
                session,
                license_record=license_record,
                binding=binding,
                trial=trial,
                now=now,
            )
            await self.events.add(
                session,
                event_type=event_type,
                result="SUCCESS",
                request_id=request.request_id,
                created_at=now,
                license_id=license_record.id,
                binding_id=binding.id,
                ip=ip,
                app_version=request.app_version,
                detail={
                    "deviceIdPrefix": device_id_prefix(request.device_id),
                    "previousDeletedTrialId": (
                        str(deleted_trial.id) if deleted_trial is not None else None
                    ),
                },
            )
            body = {
                "success": True,
                "traceId": trace_id,
                "license": envelope.as_dict(),
                "credential": credential,
                "trial": {
                    "status": trial.status.value,
                    "startedAt": trial.started_at.isoformat().replace("+00:00", "Z"),
                    "expiresAt": trial.expires_at.isoformat().replace("+00:00", "Z"),
                },
            }
            if update_advisory:
                body["update"] = update_advisory
            return await self.finish_success(
                session, endpoint=self.ENDPOINT, request_id=request.request_id, body=body
            )
        except LicenseServiceError as error:
            event_type = (
                LicenseEventType.TRIAL_EXPIRED
                if error.code == ErrorCode.TRIAL_EXPIRED
                else LicenseEventType.TRIAL_ACTIVATION_FAILED
            )
            return await self.finish_error(
                session,
                endpoint=self.ENDPOINT,
                request_id=request.request_id,
                trace_id=trace_id,
                error=error,
                event_type=event_type,
                now=now,
                ip=ip,
                app_version=request.app_version,
                detail={"deviceIdPrefix": device_id_prefix(request.device_id)},
            )
