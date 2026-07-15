from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeviceBinding, License
from app.db.models.enums import BindingStatus


class LicenseRepository:
    async def add_license(self, session: AsyncSession, license_record: License) -> License:
        session.add(license_record)
        await session.flush()
        return license_record

    async def get_by_code_hash_for_update(
        self, session: AsyncSession, license_code_hash: str
    ) -> License | None:
        statement = select(License).where(License.license_code_hash == license_code_hash).with_for_update()
        return await session.scalar(statement)

    async def get_by_id_for_update(self, session: AsyncSession, license_id: UUID) -> License | None:
        return await session.scalar(select(License).where(License.id == license_id).with_for_update())

    async def get_active_binding_for_update(
        self, session: AsyncSession, license_id: UUID
    ) -> DeviceBinding | None:
        statement: Select[tuple[DeviceBinding]] = (
            select(DeviceBinding)
            .where(
                DeviceBinding.license_id == license_id,
                DeviceBinding.status == BindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        return await session.scalar(statement)

    async def get_latest_binding_for_device(
        self, session: AsyncSession, license_id: UUID, device_id: str
    ) -> DeviceBinding | None:
        statement = (
            select(DeviceBinding)
            .where(DeviceBinding.license_id == license_id, DeviceBinding.device_id == device_id)
            .order_by(DeviceBinding.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return await session.scalar(statement)

    async def add_binding(self, session: AsyncSession, binding: DeviceBinding) -> DeviceBinding:
        session.add(binding)
        await session.flush()
        return binding

