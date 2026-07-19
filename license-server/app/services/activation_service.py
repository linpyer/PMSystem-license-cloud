from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import (
    device_id_prefix,
    generate_device_credential,
    hash_device_credential,
    hash_license_code,
    mask_license_code,
)
from app.db.models import DeviceBinding
from app.db.models.enums import BindingStatus, DeviceTrialStatus, LicenseEventType, LicenseStatus
from app.repositories.event_repository import EventRepository
from app.repositories.license_repository import LicenseRepository
from app.repositories.trial_repository import TrialRepository
from app.schemas.licenses import ActivateRequest
from app.services.idempotency_service import IdempotencyService, ServiceResult
from app.services.license_signing_service import LicenseSigningService
from app.services.service_support import LicenseOperationSupport, utc_now


class ActivationService(LicenseOperationSupport):
    ENDPOINT = "/api/v1/licenses/activate"

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

    async def activate(
        self,
        session: AsyncSession,
        request: ActivateRequest,
        *,
        trace_id: str,
        ip: str | None,
    ) -> ServiceResult:
        now = utc_now()
        payload = request.model_dump(mode="json", by_alias=True)
        replay = await self.begin_idempotent(
            session,
            endpoint=self.ENDPOINT,
            request_id=request.request_id,
            payload=payload,
            now=now,
        )
        if replay is not None:
            return replay

        try:
            update_advisory = await self.require_supported_client_policy(session, request.app_version)
            try:
                code_hash = hash_license_code(request.license_code, self.settings.code_pepper)
            except ValueError as exc:
                raise LicenseServiceError(
                    ErrorCode.INVALID_REQUEST, "Invalid licenseCode format"
                ) from exc

            license_record = await self.licenses.get_by_code_hash_for_update(session, code_hash)
            if license_record is None:
                raise LicenseServiceError(ErrorCode.LICENSE_NOT_FOUND, "License was not found")
            self.require_usable_license(license_record, now)

            binding = await self.licenses.get_active_binding_for_update(session, license_record.id)
            credential = generate_device_credential()
            credential_hash = hash_device_credential(
                credential, self.settings.device_credential_pepper
            )
            if binding is not None and binding.device_id != request.device_id:
                raise LicenseServiceError(
                    ErrorCode.LICENSE_ALREADY_BOUND,
                    "License is already bound to another device",
                    license_id=license_record.id,
                    binding_id=binding.id,
                )

            if binding is None:
                if license_record.activated_at is None:
                    license_record.activated_at = now
                    if license_record.valid_days is not None:
                        license_record.expires_at = now + timedelta(days=license_record.valid_days)
                license_record.status = LicenseStatus.ACTIVE
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
                    deactivated_at=None,
                    deactivate_reason=None,
                    last_ip=ip,
                    device_credential_hash=credential_hash,
                )
                await self.licenses.add_binding(session, binding)
                event_type = LicenseEventType.ACTIVATED
            else:
                binding.fingerprint_version = request.fingerprint_version
                binding.device_name = request.device_name
                binding.os_version = request.os_version
                binding.app_version = request.app_version
                binding.last_verified_at = now
                binding.last_ip = ip
                binding.device_credential_hash = credential_hash
                event_type = LicenseEventType.REACTIVATED_SAME_DEVICE

            await self.trials.lock_device(
                session, request.device_id, request.fingerprint_version
            )
            trial = await self.trials.get_for_device(
                session, request.device_id, request.fingerprint_version, lock=True
            )
            if trial is not None and trial.status in {
                DeviceTrialStatus.ACTIVE,
                DeviceTrialStatus.EXPIRED,
            }:
                trial.status = DeviceTrialStatus.CONVERTED
                trial.converted_at = now
                trial.converted_license_id = license_record.id
                trial.last_seen_at = now
                trial.last_ip = ip
                await self.events.add(
                    session,
                    event_type=LicenseEventType.TRIAL_CONVERTED,
                    result="SUCCESS",
                    request_id=request.request_id,
                    created_at=now,
                    license_id=trial.trial_license_id,
                    ip=ip,
                    app_version=request.app_version,
                    detail={
                        "convertedLicenseId": str(license_record.id),
                        "deviceIdPrefix": device_id_prefix(request.device_id),
                    },
                )

            envelope = await self.signing.issue(
                session, license_record=license_record, binding=binding, now=now
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
                    "licenseCode": license_record.license_code_masked,
                    "deviceIdPrefix": device_id_prefix(request.device_id),
                },
            )
            body = {
                "success": True,
                "traceId": trace_id,
                "license": envelope.as_dict(),
                "credential": credential,
            }
            if update_advisory:
                body["update"] = update_advisory
            return await self.finish_success(
                session, endpoint=self.ENDPOINT, request_id=request.request_id, body=body
            )
        except LicenseServiceError as error:
            return await self.finish_error(
                session,
                endpoint=self.ENDPOINT,
                request_id=request.request_id,
                trace_id=trace_id,
                error=error,
                event_type=LicenseEventType.ACTIVATION_FAILED,
                now=now,
                ip=ip,
                app_version=request.app_version,
                detail={
                    "licenseCode": mask_license_code(request.license_code),
                    "deviceIdPrefix": device_id_prefix(request.device_id),
                },
            )
