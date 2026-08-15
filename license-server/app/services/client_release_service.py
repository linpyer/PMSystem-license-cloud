from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from packaging.version import InvalidVersion, Version
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.update_manifest import sha256_file, utc_iso, verify_update_signature
from app.db.models import ClientRelease
from app.repositories.admin_repository import AdminRepository
from app.repositories.client_release_repository import ClientReleaseRepository
from app.schemas.client_releases import ClientReleaseDraftRequest, ClientReleaseUpdateRequest
from app.services.admin_auth_service import AuthenticatedAdmin, RequestMeta


def _version_key(version: str, build_number: int) -> tuple[Version, int]:
    try:
        return Version(version), build_number
    except InvalidVersion as exc:
        raise LicenseServiceError(ErrorCode.INVALID_REQUEST, "客户端版本格式无效") from exc


def _manifest_values(release: ClientRelease) -> dict:
    return {
        "product": release.product,
        "version": release.version,
        "buildNumber": release.build_number,
        "edition": release.edition,
        "environment": release.environment,
        "architecture": release.architecture,
        "channel": release.channel,
        "fileName": release.file_name,
        "fileSize": release.file_size,
        "sha256": release.sha256,
        "publishedAt": utc_iso(release.published_at),
    }


def _serialize(release: ClientRelease) -> dict:
    return {
        "id": str(release.id),
        **_manifest_values(release),
        "gitCommit": release.git_commit,
        "title": release.title,
        "releaseNotes": release.release_notes,
        "downloadPath": release.download_path,
        "signature": release.signature,
        "mandatory": release.mandatory,
        "status": release.status,
        "createdAt": release.created_at.isoformat() if release.created_at else None,
        "updatedAt": release.updated_at.isoformat() if release.updated_at else None,
        "createdBy": str(release.created_by) if release.created_by else None,
    }


class ClientReleaseService:
    def __init__(
        self, settings: Settings, repository: ClientReleaseRepository | None = None,
        audit_repository: AdminRepository | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or ClientReleaseRepository()
        self.audit_repository = audit_repository or AdminRepository()

    async def list(self, session: AsyncSession, page: int, page_size: int) -> dict:
        rows, total = await self.repository.list(session, page=page, page_size=page_size)
        return {"items": [_serialize(row) for row in rows], "total": total, "page": page, "pageSize": page_size}

    async def get(self, session: AsyncSession, release_id: UUID) -> ClientRelease:
        release = await self.repository.get(session, release_id)
        if release is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "客户端发布记录不存在")
        return release

    async def create_draft(
        self, session: AsyncSession, auth: AuthenticatedAdmin,
        payload: ClientReleaseDraftRequest, meta: RequestMeta,
    ) -> dict:
        duplicate = await self.repository.get_by_identity(
            session, product=payload.product, version=payload.version,
            build_number=payload.build_number, edition=payload.edition,
            environment=payload.environment, architecture=payload.architecture,
            channel=payload.channel,
        )
        if duplicate:
            raise LicenseServiceError(ErrorCode.DUPLICATE_REQUEST, "相同版本、Build和发布通道已存在")
        release = ClientRelease(
            **payload.model_dump(), status="draft", created_by=auth.user.id,
        )
        try:
            await self.repository.add(session, release)
            await self._audit(session, auth, meta, "client_release.create", release, {"status": "draft"})
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise LicenseServiceError(ErrorCode.DUPLICATE_REQUEST, "相同版本、Build和发布通道已存在") from exc
        await session.refresh(release)
        return _serialize(release)

    async def edit(
        self, session: AsyncSession, auth: AuthenticatedAdmin, release_id: UUID,
        payload: ClientReleaseUpdateRequest, meta: RequestMeta,
    ) -> dict:
        release = await self.repository.get(session, release_id, lock=True)
        if release is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "客户端发布记录不存在")
        if release.status != "draft":
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "只有草稿可以编辑")
        release.title = payload.title
        release.release_notes = payload.release_notes
        await self._audit(session, auth, meta, "client_release.edit", release, {})
        await session.commit()
        await session.refresh(release)
        return _serialize(release)

    async def publish(
        self, session: AsyncSession, auth: AuthenticatedAdmin, release_id: UUID, meta: RequestMeta,
    ) -> dict:
        release = await self.repository.get(session, release_id, lock=True)
        if release is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "客户端发布记录不存在")
        if release.status != "draft":
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "只有草稿可以发布")
        self._verify_publishable(release)
        release.status = "published"
        await self._audit(session, auth, meta, "client_release.publish", release, {"sha256": release.sha256})
        await session.commit()
        await session.refresh(release)
        return _serialize(release)

    async def withdraw(
        self, session: AsyncSession, auth: AuthenticatedAdmin, release_id: UUID, meta: RequestMeta,
    ) -> dict:
        release = await self.repository.get(session, release_id, lock=True)
        if release is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "客户端发布记录不存在")
        if release.status != "published":
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "只有已发布版本可以下架")
        release.status = "withdrawn"
        await self._audit(session, auth, meta, "client_release.withdraw", release, {})
        await session.commit()
        await session.refresh(release)
        return _serialize(release)

    async def latest(
        self, session: AsyncSession, *, product: str, edition: str, environment: str,
        architecture: str, channel: str, version: str, build_number: int,
    ) -> dict:
        current_key = _version_key(version, build_number)
        candidates = await self.repository.published_candidates(
            session, product=product, edition=edition, environment=environment,
            architecture=architecture, channel=channel,
        )
        newer = [item for item in candidates if _version_key(item.version, item.build_number) > current_key]
        if not newer:
            return {"updateAvailable": False}
        release = max(newer, key=lambda item: _version_key(item.version, item.build_number))
        manifest = _manifest_values(release)
        return {
            "updateAvailable": True,
            "version": release.version,
            "buildNumber": release.build_number,
            "gitCommit": release.git_commit,
            "edition": release.edition,
            "environment": release.environment,
            "architecture": release.architecture,
            "channel": release.channel,
            "mandatory": release.mandatory,
            "title": release.title,
            "releaseNotes": release.release_notes,
            "publishedAt": manifest["publishedAt"],
            "installer": {
                "fileName": release.file_name,
                "downloadUrl": self.settings.update_download_base_url.rstrip("/") + release.download_path,
                "fileSize": release.file_size,
                "sha256": release.sha256,
                "signature": release.signature,
            },
        }

    def _verify_publishable(self, release: ClientRelease) -> None:
        try:
            ClientReleaseDraftRequest.model_validate({
                **_manifest_values(release), "gitCommit": release.git_commit,
                "title": release.title, "releaseNotes": release.release_notes,
                "downloadPath": release.download_path, "signature": release.signature,
                "mandatory": release.mandatory,
            })
        except ValidationError as exc:
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "客户端发布元数据不合法") from exc
        root = self.settings.update_download_root.resolve()
        relative = release.download_path.removeprefix("/")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise LicenseServiceError(ErrorCode.INVALID_REQUEST, "安装包路径越界") from exc
        if path.name != release.file_name or not path.is_file():
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "安装包不存在")
        if path.stat().st_size != release.file_size:
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "安装包大小不一致")
        if sha256_file(path) != release.sha256.upper():
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "安装包SHA-256不一致")
        try:
            verify_update_signature(
                _manifest_values(release), release.signature,
                self.settings.update_signing_public_key_path,
            )
        except (InvalidSignature, ValueError, OSError) as exc:
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "更新Manifest签名无效") from exc

    async def _audit(
        self, session: AsyncSession, auth: AuthenticatedAdmin, meta: RequestMeta,
        action: str, release: ClientRelease, detail: dict,
    ) -> None:
        await self.audit_repository.add_audit(
            session, action=action, request_id=meta.request_id, trace_id=meta.trace_id,
            result="SUCCESS", now=datetime.now(timezone.utc), admin_user_id=auth.user.id,
            target_type="CLIENT_RELEASE", target_id=str(release.id), ip=meta.ip,
            user_agent=meta.user_agent, detail=detail,
        )


serialize_client_release = _serialize
