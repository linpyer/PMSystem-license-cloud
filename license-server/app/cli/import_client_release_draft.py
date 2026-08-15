from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AdminUser, ClientRelease
from app.db.models.enums import AdminRole, AdminStatus
from app.db.session import create_database_runtime
from app.repositories.admin_repository import AdminRepository
from app.repositories.client_release_repository import ClientReleaseRepository
from app.schemas.client_releases import ClientReleaseDraftRequest


async def import_stdin() -> None:
    payload = ClientReleaseDraftRequest.model_validate(json.load(sys.stdin))
    runtime = create_database_runtime(get_settings())
    try:
        async with runtime.session_factory() as session:
            owner = await session.scalar(select(AdminUser).where(
                AdminUser.role == AdminRole.OWNER, AdminUser.status == AdminStatus.ACTIVE
            ).order_by(AdminUser.created_at.asc()))
            if owner is None:
                raise RuntimeError("no active OWNER exists")
            repository = ClientReleaseRepository()
            duplicate = await repository.get_by_identity(
                session, product=payload.product, version=payload.version,
                build_number=payload.build_number, edition=payload.edition,
                environment=payload.environment, architecture=payload.architecture,
                channel=payload.channel,
            )
            if duplicate:
                raise RuntimeError(f"release identity already exists: {duplicate.id}")
            release = ClientRelease(**payload.model_dump(), status="draft", created_by=owner.id)
            await repository.add(session, release)
            request_id = str(uuid4())
            await AdminRepository().add_audit(
                session, action="client_release.create_from_publish_script",
                request_id=request_id, trace_id=request_id, result="SUCCESS",
                now=datetime.now(timezone.utc), admin_user_id=owner.id,
                target_type="CLIENT_RELEASE", target_id=str(release.id),
                detail={"status": "draft", "source": "publish_client_update.ps1"},
            )
            await session.commit()
            print(json.dumps({"id": str(release.id), "status": "draft"}))
    finally:
        await runtime.engine.dispose()


def main() -> None:
    asyncio.run(import_stdin())


if __name__ == "__main__":
    main()
