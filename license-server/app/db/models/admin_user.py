from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import AdminRole, AdminStatus


class AdminUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="admin_role", native_enum=False, create_constraint=True),
        nullable=False,
        index=True,
    )
    status: Mapped[AdminStatus] = mapped_column(
        Enum(AdminStatus, name="admin_status", native_enum=False, create_constraint=True),
        nullable=False,
        default=AdminStatus.ACTIVE,
        index=True,
    )
    totp_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_totp_counter: Mapped[int | None] = mapped_column(BigInteger)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sessions = relationship("AdminSession", back_populates="admin_user", lazy="raise")
    audit_events = relationship("AdminAuditEvent", back_populates="admin_user", lazy="raise")
