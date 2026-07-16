from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AdminLoginAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_login_attempts"
    __table_args__ = (Index("ix_admin_login_attempts_ip_created", "ip", "created_at"),)

    admin_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), index=True
    )
    username_masked: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
