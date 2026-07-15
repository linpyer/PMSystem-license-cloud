from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyRequest


class IdempotencyRepository:
    async def claim(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        endpoint: str,
        request_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> bool:
        await session.execute(
            delete(IdempotencyRequest).where(
                IdempotencyRequest.request_id == request_id,
                IdempotencyRequest.endpoint == endpoint,
                IdempotencyRequest.expires_at <= created_at,
            )
        )
        statement = (
            insert(IdempotencyRequest)
            .values(
                request_id=request_id,
                endpoint=endpoint,
                request_hash=request_hash,
                response_status=None,
                response_body=None,
                created_at=created_at,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["request_id", "endpoint"])
            .returning(IdempotencyRequest.id)
        )
        return (await session.scalar(statement)) is not None

    async def get(
        self, session: AsyncSession, *, request_id: str, endpoint: str
    ) -> IdempotencyRequest | None:
        return await session.scalar(
            select(IdempotencyRequest).where(
                IdempotencyRequest.request_id == request_id,
                IdempotencyRequest.endpoint == endpoint,
            )
        )

    async def complete(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        endpoint: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        await session.execute(
            update(IdempotencyRequest)
            .where(
                IdempotencyRequest.request_id == request_id,
                IdempotencyRequest.endpoint == endpoint,
            )
            .values(response_status=response_status, response_body=response_body)
        )
