from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeviceTrial


class TrialRepository:
    async def lock_device(
        self, session: AsyncSession, device_id: str, fingerprint_version: str
    ) -> None:
        lock_key = f"trial:{fingerprint_version}:{device_id}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    async def get_for_device(
        self,
        session: AsyncSession,
        device_id: str,
        fingerprint_version: str,
        *,
        lock: bool = False,
    ) -> DeviceTrial | None:
        statement = select(DeviceTrial).where(
            DeviceTrial.device_id == device_id,
            DeviceTrial.fingerprint_version == fingerprint_version,
            DeviceTrial.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_latest_deleted_for_device(
        self,
        session: AsyncSession,
        device_id: str,
        fingerprint_version: str,
    ) -> DeviceTrial | None:
        return await session.scalar(
            select(DeviceTrial)
            .where(
                DeviceTrial.device_id == device_id,
                DeviceTrial.fingerprint_version == fingerprint_version,
                DeviceTrial.deleted_at.is_not(None),
            )
            .order_by(DeviceTrial.deleted_at.desc())
            .limit(1)
        )

    async def get_for_license(
        self, session: AsyncSession, license_id: UUID, *, lock: bool = False
    ) -> DeviceTrial | None:
        statement = select(DeviceTrial).where(
            DeviceTrial.trial_license_id == license_id,
            DeviceTrial.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def add(self, session: AsyncSession, trial: DeviceTrial) -> DeviceTrial:
        session.add(trial)
        await session.flush()
        return trial
