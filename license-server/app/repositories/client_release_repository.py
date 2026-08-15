from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClientRelease


class ClientReleaseRepository:
    async def add(self, session: AsyncSession, release: ClientRelease) -> ClientRelease:
        session.add(release)
        await session.flush()
        return release

    async def get(self, session: AsyncSession, release_id: UUID, *, lock: bool = False) -> ClientRelease | None:
        statement = select(ClientRelease).where(ClientRelease.id == release_id)
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_by_identity(
        self, session: AsyncSession, *, product: str, version: str, build_number: int,
        edition: str, environment: str, architecture: str, channel: str,
    ) -> ClientRelease | None:
        return await session.scalar(select(ClientRelease).where(
            ClientRelease.product == product,
            ClientRelease.version == version,
            ClientRelease.build_number == build_number,
            ClientRelease.edition == edition,
            ClientRelease.environment == environment,
            ClientRelease.architecture == architecture,
            ClientRelease.channel == channel,
        ))

    async def list(self, session: AsyncSession, *, page: int, page_size: int) -> tuple[list[ClientRelease], int]:
        total = int(await session.scalar(select(func.count()).select_from(ClientRelease)) or 0)
        rows = list((await session.scalars(
            select(ClientRelease)
            .order_by(ClientRelease.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )).all())
        return rows, total

    async def published_candidates(
        self, session: AsyncSession, *, product: str, edition: str, environment: str,
        architecture: str, channel: str,
    ) -> list[ClientRelease]:
        return list((await session.scalars(
            select(ClientRelease).where(
                ClientRelease.product == product,
                ClientRelease.edition == edition,
                ClientRelease.environment == environment,
                ClientRelease.architecture == architecture,
                ClientRelease.channel == channel,
                ClientRelease.status == "published",
            )
        )).all())
