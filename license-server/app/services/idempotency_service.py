from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import request_payload_hash
from app.repositories.idempotency_repository import IdempotencyRepository


@dataclass(frozen=True, slots=True)
class ServiceResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool = False


class IdempotencyService:
    def __init__(self, repository: IdempotencyRepository, ttl_hours: int) -> None:
        self._repository = repository
        self._ttl_hours = ttl_hours

    async def begin(
        self,
        session: AsyncSession,
        *,
        endpoint: str,
        request_id: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> ServiceResult | None:
        payload_hash = request_payload_hash(payload)
        claimed = await self._repository.claim(
            session,
            request_id=request_id,
            endpoint=endpoint,
            request_hash=payload_hash,
            created_at=now,
            expires_at=now + timedelta(hours=self._ttl_hours),
        )
        if claimed:
            return None
        existing = await self._repository.get(session, request_id=request_id, endpoint=endpoint)
        if existing is None:
            raise LicenseServiceError(
                ErrorCode.SERVER_TEMPORARILY_UNAVAILABLE,
                "Request state is temporarily unavailable",
                retryable=True,
            )
        if existing.request_hash != payload_hash:
            raise LicenseServiceError(
                ErrorCode.DUPLICATE_REQUEST,
                "requestId was already used with a different request",
            )
        if existing.response_status is None or existing.response_body is None:
            raise LicenseServiceError(
                ErrorCode.DUPLICATE_REQUEST,
                "The original request is still being processed",
                retryable=True,
            )
        return ServiceResult(existing.response_status, existing.response_body, replayed=True)

    async def complete(
        self,
        session: AsyncSession,
        *,
        endpoint: str,
        request_id: str,
        status_code: int,
        body: dict[str, Any],
    ) -> None:
        await self._repository.complete(
            session,
            request_id=request_id,
            endpoint=endpoint,
            response_status=status_code,
            response_body=body,
        )

