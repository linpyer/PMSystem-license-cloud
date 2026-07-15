from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.errors import ErrorCode, LicenseServiceError
from app.core.security import request_payload_hash
from app.services.idempotency_service import IdempotencyService


class StubRepository:
    def __init__(self, *, claimed: bool, existing=None) -> None:
        self.claimed = claimed
        self.existing = existing
        self.claim_arguments = None

    async def claim(self, _session, **kwargs) -> bool:
        self.claim_arguments = kwargs
        return self.claimed

    async def get(self, _session, **_kwargs):
        return self.existing


@pytest.mark.asyncio
async def test_new_request_claim_uses_configured_expiration() -> None:
    repository = StubRepository(claimed=True)
    service = IdempotencyService(repository, ttl_hours=24)  # type: ignore[arg-type]
    now = datetime.now(timezone.utc)
    assert await service.begin(
        object(), endpoint="/activate", request_id="request-123", payload={"a": 1}, now=now
    ) is None
    assert repository.claim_arguments["expires_at"] == now + timedelta(hours=24)


@pytest.mark.asyncio
async def test_completed_request_is_replayed() -> None:
    repository = StubRepository(
        claimed=False,
        existing=SimpleNamespace(
            request_hash=request_payload_hash({"a": 1}),
            response_status=200,
            response_body={"success": True},
        ),
    )
    service = IdempotencyService(repository, ttl_hours=24)  # type: ignore[arg-type]
    result = await service.begin(
        object(),
        endpoint="/activate",
        request_id="request-123",
        payload={"a": 1},
        now=datetime.now(timezone.utc),
    )
    assert result is not None
    assert result.replayed is True
    assert result.body == {"success": True}


@pytest.mark.asyncio
async def test_reused_request_id_with_different_payload_is_rejected() -> None:
    repository = StubRepository(
        claimed=False,
        existing=SimpleNamespace(
            request_hash="different",
            response_status=200,
            response_body={"success": True},
        ),
    )
    service = IdempotencyService(repository, ttl_hours=24)  # type: ignore[arg-type]
    with pytest.raises(LicenseServiceError) as captured:
        await service.begin(
            object(),
            endpoint="/activate",
            request_id="request-123",
            payload={"a": 1},
            now=datetime.now(timezone.utc),
        )
    assert captured.value.code == ErrorCode.DUPLICATE_REQUEST
