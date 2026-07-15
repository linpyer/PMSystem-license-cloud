from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import credential_matches, device_id_prefix
from app.db.models.enums import BindingStatus, LicenseEventType
from app.repositories.event_repository import EventRepository
from app.repositories.license_repository import LicenseRepository
from app.schemas.licenses import DeactivateRequest
from app.services.idempotency_service import IdempotencyService, ServiceResult
from app.services.service_support import LicenseOperationSupport, utc_now


class DeactivationService(LicenseOperationSupport):
    ENDPOINT = "/api/v1/licenses/deactivate"

    def __init__(
        self,
        settings: Settings,
        *,
        licenses: LicenseRepository | None = None,
        events: EventRepository | None = None,
        idempotency: IdempotencyService,
    ) -> None:
        event_repository = events or EventRepository()
        super().__init__(settings, idempotency, event_repository)
        self.licenses = licenses or LicenseRepository()

    async def deactivate(
        self,
        session: AsyncSession,
        request: DeactivateRequest,
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
            license_record = await self.licenses.get_by_id_for_update(session, request.license_id)
            if license_record is None:
                raise LicenseServiceError(ErrorCode.LICENSE_NOT_FOUND, "License was not found")
            binding = await self.licenses.get_active_binding_for_update(session, license_record.id)
            already_deactivated = False
            if binding is None:
                latest = await self.licenses.get_latest_binding_for_device(
                    session, license_record.id, request.device_id
                )
                if latest is None:
                    raise LicenseServiceError(
                        ErrorCode.DEVICE_MISMATCH,
                        "No binding history exists for this device",
                        license_id=license_record.id,
                    )
                if latest is not None and latest.status == BindingStatus.DISABLED:
                    raise LicenseServiceError(
                        ErrorCode.DEVICE_DISABLED,
                        "Device binding is disabled",
                        license_id=license_record.id,
                        binding_id=latest.id,
                    )
                if not credential_matches(
                    request.credential,
                    latest.device_credential_hash,
                    self.settings.device_credential_pepper,
                ):
                    raise LicenseServiceError(
                        ErrorCode.INVALID_CREDENTIAL,
                        "Device credential is invalid",
                        license_id=license_record.id,
                        binding_id=latest.id,
                    )
                binding = latest
                already_deactivated = True
            elif binding.device_id != request.device_id:
                raise LicenseServiceError(
                    ErrorCode.DEVICE_MISMATCH,
                    "Device does not match the active binding",
                    license_id=license_record.id,
                    binding_id=binding.id,
                )
            elif not credential_matches(
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
            else:
                binding.status = BindingStatus.DEACTIVATED
                binding.deactivated_at = now
                binding.deactivate_reason = request.reason
                binding.last_ip = ip

            await self.events.add(
                session,
                event_type=LicenseEventType.DEACTIVATED,
                result="ALREADY_DEACTIVATED" if already_deactivated else "SUCCESS",
                request_id=request.request_id,
                created_at=now,
                license_id=license_record.id,
                binding_id=binding.id if binding is not None else None,
                ip=ip,
                detail={"deviceIdPrefix": device_id_prefix(request.device_id)},
            )
            body = {
                "success": True,
                "traceId": trace_id,
                "deactivated": True,
                "alreadyDeactivated": already_deactivated,
            }
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
                event_type=LicenseEventType.DEACTIVATION_FAILED,
                now=now,
                ip=ip,
                app_version=None,
                detail={"deviceIdPrefix": device_id_prefix(request.device_id)},
            )
