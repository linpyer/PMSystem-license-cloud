from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SigningKey
from app.db.models.enums import SigningKeyStatus


class SigningKeyRepository:
    async def ensure_active_key(
        self,
        session: AsyncSession,
        *,
        key_id: str,
        public_key: str,
        now: datetime,
    ) -> SigningKey:
        existing = await session.scalar(select(SigningKey).where(SigningKey.key_id == key_id))
        if existing is not None:
            if existing.public_key != public_key or existing.algorithm != "Ed25519":
                raise ValueError("signing key id already exists with different public material")
            if existing.status != SigningKeyStatus.ACTIVE:
                raise ValueError("configured signing key is not active")
            return existing
        record = SigningKey(
            key_id=key_id,
            algorithm="Ed25519",
            public_key=public_key,
            status=SigningKeyStatus.ACTIVE,
            activated_at=now,
            retired_at=None,
            created_at=now,
        )
        session.add(record)
        await session.flush()
        return record

