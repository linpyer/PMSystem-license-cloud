from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.db.models import AppVersionPolicy
from app.db.models.enums import BindingStatus, LicenseEventType, LicenseStatus
from app.repositories.admin_repository import AdminRepository
from app.repositories.event_repository import EventRepository
from app.repositories.idempotency_repository import IdempotencyRepository
from app.schemas.admin import (
    AuditQuery,
    LicenseBatchCreateRequest,
    LicenseCreateRequest,
    LicenseListQuery,
    LicenseUpdateRequest,
    ReasonRequest,
    VersionPolicyRequest,
)
from app.services.admin_auth_service import AuthenticatedAdmin, RequestMeta
from app.services.idempotency_service import IdempotencyService, ServiceResult
from app.services.license_code_service import LicenseCodeService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _masked_device(device_id: str | None) -> str | None:
    return f"{device_id[:8]}..." if device_id else None


class AdminManagementService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = AdminRepository()
        self.events = EventRepository()
        self.codes = LicenseCodeService(settings)
        self.idempotency = IdempotencyService(IdempotencyRepository(), settings.idempotency_ttl_hours)

    async def create_licenses(
        self,
        session: AsyncSession,
        auth: AuthenticatedAdmin,
        request: LicenseCreateRequest | LicenseBatchCreateRequest,
        meta: RequestMeta,
    ) -> ServiceResult:
        now = _utc_now()
        endpoint = "/api/v1/admin/licenses/batch" if isinstance(request, LicenseBatchCreateRequest) else "/api/v1/admin/licenses"
        payload = request.model_dump(mode="json", by_alias=True)
        replay = await self.idempotency.begin(
            session, endpoint=endpoint, request_id=request.request_id, payload=payload, now=now
        )
        if replay is not None:
            await session.commit()
            return replay

        quantity = request.quantity if isinstance(request, LicenseBatchCreateRequest) else 1
        created = []
        for _ in range(quantity):
            item = await self.codes.create(
                session,
                license_type=request.license_type,
                expires_at=request.expires_at,
                customer_name=request.customer_name,
                customer_contact=request.customer_contact,
                remark=request.remark,
            )
            created.append(item)
        safe_items = [
            {
                "licenseId": str(item.record.id),
                "maskedCode": item.record.license_code_masked,
                "licenseType": item.record.license_type.value,
                "expiresAt": _iso(item.record.expires_at),
            }
            for item in created
        ]
        replay_body = {
            "success": True,
            "traceId": meta.trace_id,
            "items": safe_items,
            "plaintextAvailable": False,
            "message": "该请求已处理，明文激活码仅在首次响应中显示",
        }
        await self.idempotency.complete(
            session, endpoint=endpoint, request_id=request.request_id,
            status_code=201, body=replay_body,
        )
        await self.repository.add_audit(
            session,
            action="BATCH_CREATE_LICENSE" if quantity > 1 else "CREATE_LICENSE",
            request_id=request.request_id,
            trace_id=meta.trace_id,
            result="SUCCESS",
            now=now,
            admin_user_id=auth.user.id,
            target_type="license_batch" if quantity > 1 else "license",
            target_id=str(created[0].record.id) if quantity == 1 else request.request_id,
            ip=meta.ip,
            user_agent=meta.user_agent,
            detail={"count": quantity, "licenseType": request.license_type.value},
        )
        await session.commit()
        body = {
            **replay_body,
            "items": [
                {**safe, "licenseCode": item.plaintext_code}
                for safe, item in zip(safe_items, created, strict=True)
            ],
            "plaintextAvailable": True,
            "message": "完整激活码仅显示一次，请立即安全保存",
        }
        return ServiceResult(201, body)

    async def list_licenses(self, session: AsyncSession, query: LicenseListQuery) -> dict[str, Any]:
        rows, total = await self.repository.list_licenses(session, **query.model_dump())
        items = []
        for license_record, binding_id, device_id, last_verified_at in rows:
            items.append(
                {
                    "licenseId": str(license_record.id),
                    "maskedCode": license_record.license_code_masked,
                    "licenseType": license_record.license_type.value,
                    "status": license_record.status.value,
                    "customerName": license_record.customer_name,
                    "customerContact": license_record.customer_contact,
                    "activatedAt": _iso(license_record.activated_at),
                    "expiresAt": _iso(license_record.expires_at),
                    "createdAt": _iso(license_record.created_at),
                    "bindingId": str(binding_id) if binding_id else None,
                    "device": _masked_device(device_id),
                    "lastVerifiedAt": _iso(last_verified_at),
                }
            )
        return {"items": items, "page": query.page, "pageSize": query.page_size, "total": total}

    async def license_detail(self, session: AsyncSession, license_id: UUID) -> dict[str, Any]:
        record = await self.repository.get_license(session, license_id)
        if record is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "授权不存在")
        bindings = await self.repository.list_bindings(session, license_id)
        events = await self.repository.license_events(session, license_id)
        return {
            "licenseId": str(record.id),
            "maskedCode": record.license_code_masked,
            "licenseType": record.license_type.value,
            "status": record.status.value,
            "customerName": record.customer_name,
            "customerContact": record.customer_contact,
            "remark": record.remark,
            "activatedAt": _iso(record.activated_at),
            "expiresAt": _iso(record.expires_at),
            "createdAt": _iso(record.created_at),
            "updatedAt": _iso(record.updated_at),
            "bindings": [self._binding_dict(item) for item in bindings],
            "events": [self._event_dict(item) for item in events],
            "renewalAvailable": False,
        }

    async def update_license(
        self, session: AsyncSession, auth: AuthenticatedAdmin, license_id: UUID,
        request: LicenseUpdateRequest, meta: RequestMeta,
    ) -> dict[str, Any]:
        record = await self._locked_license(session, license_id)
        changes = request.model_dump()
        for key, value in changes.items():
            setattr(record, key, value)
        await self._audit(session, auth, meta, "UPDATE_LICENSE", "license", license_id, {"fields": list(changes)})
        await session.commit()
        return await self.license_detail(session, license_id)

    async def change_status(
        self, session: AsyncSession, auth: AuthenticatedAdmin, license_id: UUID,
        action: str, request: ReasonRequest, meta: RequestMeta,
    ) -> dict[str, Any]:
        record = await self._locked_license(session, license_id)
        transitions = {
            "disable": ({LicenseStatus.CREATED, LicenseStatus.ACTIVE}, LicenseStatus.DISABLED, LicenseEventType.LICENSE_DISABLED),
            "enable": ({LicenseStatus.DISABLED}, LicenseStatus.ACTIVE if record.activated_at else LicenseStatus.CREATED, LicenseEventType.LICENSE_ENABLED),
            "revoke": ({LicenseStatus.CREATED, LicenseStatus.ACTIVE, LicenseStatus.DISABLED}, LicenseStatus.REVOKED, LicenseEventType.LICENSE_REVOKED),
        }
        allowed, target, event_type = transitions[action]
        if record.status not in allowed:
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "当前授权状态不允许执行此操作")
        record.status = target
        now = _utc_now()
        await self.events.add(
            session, event_type=event_type, result="SUCCESS", request_id=meta.request_id,
            created_at=now, license_id=record.id, ip=meta.ip,
            detail={"reason": request.reason, "adminUserId": str(auth.user.id)},
        )
        await self._audit(
            session, auth, meta, f"{action.upper()}_LICENSE", "license", license_id,
            {"reason": request.reason, "status": target.value}, now,
        )
        await session.commit()
        return {"licenseId": str(record.id), "status": record.status.value}

    async def deactivate_binding(
        self, session: AsyncSession, auth: AuthenticatedAdmin, binding_id: UUID,
        request: ReasonRequest, meta: RequestMeta,
    ) -> dict[str, Any]:
        binding = await self.repository.get_binding(session, binding_id, lock=True)
        if binding is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "设备绑定不存在")
        now = _utc_now()
        if binding.status == BindingStatus.ACTIVE:
            binding.status = BindingStatus.DEACTIVATED
            binding.deactivated_at = now
            binding.deactivate_reason = request.reason
        await self.events.add(
            session, event_type=LicenseEventType.ADMIN_DEACTIVATED, result="SUCCESS",
            request_id=meta.request_id, created_at=now, license_id=binding.license_id,
            binding_id=binding.id, ip=meta.ip,
            detail={"reason": request.reason, "adminUserId": str(auth.user.id)},
        )
        await self._audit(
            session, auth, meta, "DEACTIVATE_BINDING", "device_binding", binding.id,
            {"reason": request.reason, "licenseId": str(binding.license_id)}, now,
        )
        await session.commit()
        return {"bindingId": str(binding.id), "status": binding.status.value}

    async def dashboard(self, session: AsyncSession) -> dict[str, Any]:
        metrics = await self.repository.dashboard_summary(session, _utc_now())
        recent = await self.repository.dashboard_recent(session)
        for items in recent.values():
            for item in items:
                for key, value in tuple(item.items()):
                    if isinstance(value, datetime):
                        item[key] = _iso(value)
        return {"summary": metrics, "recent": recent}

    async def list_admin_audit(self, session: AsyncSession, query: AuditQuery) -> dict[str, Any]:
        rows, total = await self.repository.audit_events(session, **query.model_dump())
        return {
            "items": [
                {
                    "id": str(item.id), "adminUserId": str(item.admin_user_id) if item.admin_user_id else None,
                    "action": item.action, "targetType": item.target_type, "targetId": item.target_id,
                    "result": item.result, "detail": item.detail, "createdAt": _iso(item.created_at),
                }
                for item in rows
            ],
            "page": query.page, "pageSize": query.page_size, "total": total,
        }

    async def list_license_events(self, session: AsyncSession, page: int, page_size: int) -> dict[str, Any]:
        rows, total = await self.repository.all_license_events(session, page=page, page_size=page_size)
        return {"items": [self._event_dict(item) for item in rows], "page": page, "pageSize": page_size, "total": total}

    async def get_version_policy(self, session: AsyncSession) -> dict[str, Any]:
        policy = await self.repository.get_version_policy(session)
        if policy is None:
            return {
                "product": "PMSystem", "platform": "windows",
                "recommendedVersion": self.settings.minimum_client_version,
                "minimumSupportedVersion": self.settings.minimum_client_version,
                "downloadUrl": None, "releaseNotes": None, "updatedAt": None,
            }
        return self._version_dict(policy)

    async def save_version_policy(
        self, session: AsyncSession, auth: AuthenticatedAdmin,
        request: VersionPolicyRequest, meta: RequestMeta,
    ) -> dict[str, Any]:
        if semantic_version(request.minimum_supported_version) > semantic_version(request.recommended_version):
            raise LicenseServiceError(ErrorCode.INVALID_REQUEST, "最低支持版本不能高于推荐版本")
        now = _utc_now()
        policy = await self.repository.get_version_policy(session)
        if policy is None:
            policy = AppVersionPolicy(product="PMSystem", platform="windows")
            session.add(policy)
        policy.recommended_version = request.recommended_version
        policy.minimum_supported_version = request.minimum_supported_version
        policy.download_url = str(request.download_url) if request.download_url else None
        policy.release_notes = request.release_notes
        policy.updated_by = auth.user.id
        policy.updated_at = now
        await session.flush()
        await self._audit(session, auth, meta, "UPDATE_VERSION_POLICY", "version_policy", policy.id, {
            "recommendedVersion": request.recommended_version,
            "minimumSupportedVersion": request.minimum_supported_version,
        }, now)
        await session.commit()
        return self._version_dict(policy)

    async def _locked_license(self, session: AsyncSession, license_id: UUID):
        record = await self.repository.get_license(session, license_id, lock=True)
        if record is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "授权不存在")
        return record

    async def _audit(
        self, session: AsyncSession, auth: AuthenticatedAdmin, meta: RequestMeta,
        action: str, target_type: str, target_id: UUID, detail: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        await self.repository.add_audit(
            session, action=action, request_id=meta.request_id, trace_id=meta.trace_id,
            result="SUCCESS", now=now or _utc_now(), admin_user_id=auth.user.id,
            target_type=target_type, target_id=str(target_id), ip=meta.ip,
            user_agent=meta.user_agent, detail=detail,
        )

    @staticmethod
    def _binding_dict(item) -> dict[str, Any]:
        return {
            "bindingId": str(item.id), "device": _masked_device(item.device_id),
            "deviceName": item.device_name, "osVersion": item.os_version,
            "appVersion": item.app_version, "status": item.status.value,
            "firstActivatedAt": _iso(item.first_activated_at),
            "lastVerifiedAt": _iso(item.last_verified_at),
            "deactivatedAt": _iso(item.deactivated_at), "deactivateReason": item.deactivate_reason,
        }

    @staticmethod
    def _event_dict(item) -> dict[str, Any]:
        return {
            "id": str(item.id), "licenseId": str(item.license_id) if item.license_id else None,
            "bindingId": str(item.binding_id) if item.binding_id else None,
            "eventType": item.event_type.value, "result": item.result,
            "requestId": item.request_id, "detail": item.detail, "createdAt": _iso(item.created_at),
        }

    @staticmethod
    def _version_dict(policy: AppVersionPolicy) -> dict[str, Any]:
        return {
            "product": policy.product, "platform": policy.platform,
            "recommendedVersion": policy.recommended_version,
            "minimumSupportedVersion": policy.minimum_supported_version,
            "downloadUrl": policy.download_url, "releaseNotes": policy.release_notes,
            "updatedAt": _iso(policy.updated_at),
        }


def semantic_version(value: str) -> tuple[int, int, int, str]:
    core, _, suffix = value.partition("-")
    parts = core.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2]), suffix
