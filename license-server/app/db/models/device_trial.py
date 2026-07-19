from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import DeviceTrialStatus


class DeviceTrial(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_trials"
    __table_args__ = (
        UniqueConstraint("trial_license_id", name="uq_device_trials_trial_license_id"),
        CheckConstraint(
            "expires_at > started_at",
            name="valid_time_range",
        ),
        Index(
            "uq_device_trials_active_device_fingerprint",
            "device_id",
            "fingerprint_version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_device_trials_status", "status"),
        Index("ix_device_trials_expires_at", "expires_at"),
        Index("ix_device_trials_last_seen_at", "last_seen_at"),
        Index("ix_device_trials_deleted_at", "deleted_at"),
    )

    device_id: Mapped[str] = mapped_column(String(200), nullable=False)
    fingerprint_version: Mapped[str] = mapped_column(String(40), nullable=False)
    trial_license_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("licenses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[DeviceTrialStatus] = mapped_column(
        Enum(
            DeviceTrialStatus,
            name="device_trial_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=DeviceTrialStatus.ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_license_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("licenses.id", ondelete="RESTRICT")
    )
    first_ip: Mapped[str | None] = mapped_column(INET)
    last_ip: Mapped[str | None] = mapped_column(INET)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(200))
    os_version: Mapped[str | None] = mapped_column(String(160))
    app_version: Mapped[str] = mapped_column(String(40), nullable=False)
    reset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reset_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    last_reset_reason: Mapped[str | None] = mapped_column(Text)
    extension_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_extended_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_extended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_extended_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    last_extension_days: Mapped[int | None] = mapped_column(Integer)
    last_extension_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)

    trial_license = relationship(
        "License", back_populates="trial", foreign_keys=[trial_license_id], lazy="raise"
    )
    converted_license = relationship("License", foreign_keys=[converted_license_id], lazy="raise")
