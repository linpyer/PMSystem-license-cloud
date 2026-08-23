from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ClientRelease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "client_releases"
    __table_args__ = (
        UniqueConstraint(
            "product", "version", "build_number", "edition", "environment",
            "architecture", "channel", name="uq_client_release_identity",
        ),
        CheckConstraint("edition IN ('standard','license')", name="client_release_edition"),
        # Keep legacy database values readable; request schemas reject new local/dev rows.
        CheckConstraint("environment IN ('local','production')", name="client_release_environment"),
        CheckConstraint("architecture IN ('x64')", name="client_release_architecture"),
        CheckConstraint("channel IN ('stable','dev')", name="client_release_channel"),
        CheckConstraint("status IN ('draft','published','withdrawn')", name="client_release_status"),
        CheckConstraint("build_number > 0", name="client_release_positive_build"),
        CheckConstraint("file_size > 0", name="client_release_positive_size"),
        Index(
            "ix_client_releases_lookup", "product", "edition", "environment",
            "architecture", "channel", "status", "published_at",
        ),
    )

    product: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    edition: Mapped[str] = mapped_column(String(20), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    architecture: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(260), nullable=False)
    download_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), index=True
    )
