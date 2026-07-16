from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminAuditEvent,
    AdminLoginAttempt,
    AdminSession,
    AdminUser,
    AppVersionPolicy,
    DeviceBinding,
    License,
    LicenseEvent,
)
from app.db.models.enums import AdminSessionStatus, BindingStatus, LicenseStatus


class AdminRepository:
    async def get_user_by_username(self, session: AsyncSession, username: str) -> AdminUser | None:
        return await session.scalar(
            select(AdminUser).where(func.lower(AdminUser.username) == username.strip().lower())
        )

    async def get_user(self, session: AsyncSession, user_id: UUID) -> AdminUser | None:
        return await session.get(AdminUser, user_id)

    async def add_user(self, session: AsyncSession, user: AdminUser) -> AdminUser:
        session.add(user)
        await session.flush()
        return user

    async def list_users(self, session: AsyncSession) -> list[AdminUser]:
        return list(
            (await session.scalars(select(AdminUser).order_by(AdminUser.created_at.asc()))).all()
        )

    async def add_session(self, session: AsyncSession, record: AdminSession) -> AdminSession:
        session.add(record)
        await session.flush()
        return record

    async def get_session_by_hash(
        self, session: AsyncSession, token_hash: str, *, for_update: bool = False
    ) -> AdminSession | None:
        statement = select(AdminSession).where(AdminSession.token_hash == token_hash)
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def revoke_user_sessions(
        self, session: AsyncSession, user_id: UUID, now: datetime, *, except_id: UUID | None = None
    ) -> None:
        conditions = [
            AdminSession.admin_user_id == user_id,
            AdminSession.status != AdminSessionStatus.REVOKED,
        ]
        if except_id is not None:
            conditions.append(AdminSession.id != except_id)
        await session.execute(
            update(AdminSession)
            .where(*conditions)
            .values(status=AdminSessionStatus.REVOKED, revoked_at=now)
        )

    async def add_login_attempt(
        self,
        session: AsyncSession,
        *,
        username_masked: str,
        stage: str,
        result: str,
        ip: str | None,
        now: datetime,
        admin_user_id: UUID | None = None,
    ) -> None:
        session.add(
            AdminLoginAttempt(
                admin_user_id=admin_user_id,
                username_masked=username_masked,
                stage=stage,
                result=result,
                ip=ip,
                created_at=now,
            )
        )
        await session.flush()

    async def recent_ip_failures(
        self, session: AsyncSession, ip: str | None, now: datetime, minutes: int
    ) -> int:
        if not ip:
            return 0
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AdminLoginAttempt)
                .where(
                    AdminLoginAttempt.ip == ip,
                    AdminLoginAttempt.result == "FAILED",
                    AdminLoginAttempt.created_at >= now - timedelta(minutes=minutes),
                )
            )
            or 0
        )

    async def add_audit(
        self,
        session: AsyncSession,
        *,
        action: str,
        request_id: str,
        trace_id: str,
        result: str,
        now: datetime,
        admin_user_id: UUID | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AdminAuditEvent:
        event = AdminAuditEvent(
            admin_user_id=admin_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            trace_id=trace_id,
            ip=ip,
            user_agent=user_agent,
            result=result,
            detail=detail or {},
            created_at=now,
        )
        session.add(event)
        await session.flush()
        return event

    async def get_license(self, session: AsyncSession, license_id: UUID, *, lock: bool = False) -> License | None:
        statement = select(License).where(License.id == license_id)
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list_licenses(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        keyword: str | None,
        license_type: Any,
        status: Any,
        bound: bool | None,
        sort_by: str,
        sort_order: str,
        created_from: datetime | None,
        created_to: datetime | None,
        expires_from: datetime | None,
        expires_to: datetime | None,
        verified_from: datetime | None,
        verified_to: datetime | None,
    ) -> tuple[list[tuple[License, UUID | None, str | None, datetime | None]], int]:
        active_binding = (
            select(
                DeviceBinding.license_id.label("license_id"),
                DeviceBinding.id.label("binding_id"),
                DeviceBinding.device_id.label("device_id"),
                DeviceBinding.last_verified_at.label("last_verified_at"),
            )
            .where(DeviceBinding.status == BindingStatus.ACTIVE)
            .subquery()
        )
        conditions = []
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    License.license_code_masked.ilike(pattern),
                    License.customer_name.ilike(pattern),
                    License.customer_contact.ilike(pattern),
                    func.cast(License.id, String).ilike(pattern),
                )
            )
        if license_type is not None:
            conditions.append(License.license_type == license_type)
        if status is not None:
            conditions.append(License.status == status)
        if bound is True:
            conditions.append(active_binding.c.binding_id.is_not(None))
        elif bound is False:
            conditions.append(active_binding.c.binding_id.is_(None))
        for column, start, end in (
            (License.created_at, created_from, created_to),
            (License.expires_at, expires_from, expires_to),
            (active_binding.c.last_verified_at, verified_from, verified_to),
        ):
            if start:
                conditions.append(column >= start)
            if end:
                conditions.append(column <= end)

        base = select(License).outerjoin(active_binding, active_binding.c.license_id == License.id)
        count_statement = select(func.count()).select_from(License).outerjoin(
            active_binding, active_binding.c.license_id == License.id
        )
        if conditions:
            base = base.where(*conditions)
            count_statement = count_statement.where(*conditions)
        sort_columns = {
            "createdAt": License.created_at,
            "expiresAt": License.expires_at,
            "activatedAt": License.activated_at,
            "lastVerifiedAt": active_binding.c.last_verified_at,
        }
        sort_column = sort_columns[sort_by]
        order = sort_column.asc().nullslast() if sort_order == "asc" else sort_column.desc().nullslast()
        statement = (
            base.with_only_columns(
                License,
                active_binding.c.binding_id,
                active_binding.c.device_id,
                active_binding.c.last_verified_at,
            )
            .order_by(order, License.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await session.execute(statement)).all())
        total = int(await session.scalar(count_statement) or 0)
        return rows, total

    async def list_bindings(self, session: AsyncSession, license_id: UUID) -> list[DeviceBinding]:
        return list(
            (await session.scalars(
                select(DeviceBinding)
                .where(DeviceBinding.license_id == license_id)
                .order_by(DeviceBinding.created_at.desc())
            )).all()
        )

    async def get_binding(self, session: AsyncSession, binding_id: UUID, *, lock: bool = False) -> DeviceBinding | None:
        statement = select(DeviceBinding).where(DeviceBinding.id == binding_id)
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def license_events(self, session: AsyncSession, license_id: UUID, limit: int = 50) -> list[LicenseEvent]:
        return list(
            (await session.scalars(
                select(LicenseEvent)
                .where(LicenseEvent.license_id == license_id)
                .order_by(LicenseEvent.created_at.desc())
                .limit(limit)
            )).all()
        )

    async def audit_events(
        self, session: AsyncSession, *, page: int, page_size: int, action: str | None,
        target_id: str | None, admin_user_id: UUID | None, created_from: datetime | None,
        created_to: datetime | None,
    ) -> tuple[list[AdminAuditEvent], int]:
        conditions = []
        if action:
            conditions.append(AdminAuditEvent.action == action)
        if target_id:
            conditions.append(AdminAuditEvent.target_id.ilike(f"%{target_id}%"))
        if admin_user_id:
            conditions.append(AdminAuditEvent.admin_user_id == admin_user_id)
        if created_from:
            conditions.append(AdminAuditEvent.created_at >= created_from)
        if created_to:
            conditions.append(AdminAuditEvent.created_at <= created_to)
        base = select(AdminAuditEvent)
        count = select(func.count()).select_from(AdminAuditEvent)
        if conditions:
            base = base.where(*conditions)
            count = count.where(*conditions)
        rows = list((await session.scalars(
            base.order_by(AdminAuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).all())
        return rows, int(await session.scalar(count) or 0)

    async def all_license_events(self, session: AsyncSession, *, page: int, page_size: int) -> tuple[list[LicenseEvent], int]:
        total = int(await session.scalar(select(func.count()).select_from(LicenseEvent)) or 0)
        rows = list((await session.scalars(
            select(LicenseEvent).order_by(LicenseEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).all())
        return rows, total

    async def dashboard_summary(self, session: AsyncSession, now: datetime) -> dict[str, int]:
        row = (await session.execute(
            select(
                func.count(License.id),
                func.count(License.id).filter(License.activated_at.is_not(None)),
                func.count(License.id).filter(License.activated_at.is_(None)),
                func.count(License.id).filter(License.status == LicenseStatus.ACTIVE),
                func.count(License.id).filter(License.status == LicenseStatus.EXPIRED),
                func.count(License.id).filter(License.status == LicenseStatus.DISABLED),
                func.count(License.id).filter(License.status == LicenseStatus.REVOKED),
                func.count(License.id).filter(and_(License.expires_at > now, License.expires_at <= now + timedelta(days=7))),
                func.count(License.id).filter(and_(License.expires_at > now, License.expires_at <= now + timedelta(days=30))),
                func.count(License.id).filter(License.created_at >= now - timedelta(days=7)),
                func.count(License.id).filter(License.activated_at >= now - timedelta(days=7)),
            )
        )).one()
        active_bindings = int(await session.scalar(
            select(func.count()).select_from(DeviceBinding).where(DeviceBinding.status == BindingStatus.ACTIVE)
        ) or 0)
        verified_24h = int(await session.scalar(
            select(func.count()).select_from(DeviceBinding).where(
                DeviceBinding.status == BindingStatus.ACTIVE,
                DeviceBinding.last_verified_at >= now - timedelta(hours=24),
            )
        ) or 0)
        names = ("total", "activated", "unactivated", "active", "expired", "disabled", "revoked", "expiring7Days", "expiring30Days", "created7Days", "activated7Days")
        result = {name: int(value or 0) for name, value in zip(names, row, strict=True)}
        result.update(activeBindings=active_bindings, verified24Hours=verified_24h)
        return result

    async def dashboard_recent(self, session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
        created = list((await session.scalars(
            select(License).order_by(License.created_at.desc()).limit(5)
        )).all())
        activated = list((await session.scalars(
            select(License).where(License.activated_at.is_not(None))
            .order_by(License.activated_at.desc()).limit(5)
        )).all())
        admin_events = list((await session.scalars(
            select(AdminAuditEvent).order_by(AdminAuditEvent.created_at.desc()).limit(5)
        )).all())
        abnormal = list((await session.scalars(
            select(LicenseEvent).where(LicenseEvent.result != "SUCCESS")
            .order_by(LicenseEvent.created_at.desc()).limit(5)
        )).all())
        return {
            "createdLicenses": [
                {
                    "id": str(item.id), "maskedCode": item.license_code_masked,
                    "customerName": item.customer_name, "status": item.status.value,
                    "createdAt": item.created_at,
                }
                for item in created
            ],
            "recentActivations": [
                {
                    "id": str(item.id), "maskedCode": item.license_code_masked,
                    "customerName": item.customer_name, "activatedAt": item.activated_at,
                }
                for item in activated
            ],
            "adminOperations": [
                {
                    "id": str(item.id), "action": item.action, "result": item.result,
                    "targetId": item.target_id, "createdAt": item.created_at,
                }
                for item in admin_events
            ],
            "abnormalEvents": [
                {
                    "id": str(item.id), "eventType": item.event_type.value,
                    "result": item.result, "licenseId": str(item.license_id) if item.license_id else None,
                    "createdAt": item.created_at,
                }
                for item in abnormal
            ],
        }

    async def get_version_policy(self, session: AsyncSession) -> AppVersionPolicy | None:
        return await session.scalar(
            select(AppVersionPolicy).where(
                AppVersionPolicy.product == "PMSystem", AppVersionPolicy.platform == "windows"
            )
        )
