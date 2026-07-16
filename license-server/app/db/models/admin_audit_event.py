from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class AdminAuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_audit_events"
    __table_args__ = (
        Index("ix_admin_audit_events_created_at", "created_at"),
        Index("ix_admin_audit_events_action", "action"),
        Index("ix_admin_audit_events_target", "target_type", "target_id"),
    )

    admin_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    admin_user = relationship("AdminUser", back_populates="audit_events", lazy="raise")
