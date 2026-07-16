from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AppVersionPolicy(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "app_version_policy"
    __table_args__ = (UniqueConstraint("product", "platform", name="uq_app_version_product_platform"),)

    product: Mapped[str] = mapped_column(String(80), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    recommended_version: Mapped[str] = mapped_column(String(40), nullable=False)
    minimum_supported_version: Mapped[str] = mapped_column(String(40), nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(1000))
    release_notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
