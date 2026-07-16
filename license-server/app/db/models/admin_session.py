from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.models.enums import AdminSessionStatus


class AdminSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        Index("ix_admin_sessions_user_status", "admin_user_id", "status"),
        Index("ix_admin_sessions_expires_at", "expires_at"),
    )

    admin_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[AdminSessionStatus] = mapped_column(
        Enum(
            AdminSessionStatus,
            name="admin_session_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        index=True,
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    admin_user = relationship("AdminUser", back_populates="sessions", lazy="raise")
