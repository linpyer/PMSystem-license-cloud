from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminSession, IdempotencyRequest


@dataclass(frozen=True, slots=True)
class CleanupResult:
    expired_sessions: int
    expired_idempotency_requests: int


async def cleanup_expired_records(session: AsyncSession, now: datetime) -> CleanupResult:
    sessions = await session.execute(
        delete(AdminSession).where(AdminSession.expires_at < now)
    )
    requests = await session.execute(
        delete(IdempotencyRequest).where(IdempotencyRequest.expires_at < now)
    )
    await session.commit()
    return CleanupResult(
        expired_sessions=int(sessions.rowcount or 0),
        expired_idempotency_requests=int(requests.rowcount or 0),
    )
