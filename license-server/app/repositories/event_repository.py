from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LicenseEvent
from app.db.models.enums import LicenseEventType


class EventRepository:
    async def add(
        self,
        session: AsyncSession,
        *,
        event_type: LicenseEventType,
        result: str,
        request_id: str,
        created_at: datetime,
        license_id: UUID | None = None,
        binding_id: UUID | None = None,
        ip: str | None = None,
        app_version: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> LicenseEvent:
        event = LicenseEvent(
            license_id=license_id,
            binding_id=binding_id,
            event_type=event_type,
            result=result,
            request_id=request_id,
            ip=ip,
            app_version=app_version,
            detail=detail or {},
            created_at=created_at,
        )
        session.add(event)
        await session.flush()
        return event

