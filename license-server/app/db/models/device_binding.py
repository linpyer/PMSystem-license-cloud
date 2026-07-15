from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INET, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import BindingStatus


class DeviceBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_bindings"
    __table_args__ = (
        Index(
            "uq_device_bindings_active_license",
            "license_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_device_bindings_device_id", "device_id"),
    )

    license_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("licenses.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(200), nullable=False)
    fingerprint_version: Mapped[str] = mapped_column(String(40), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(200))
    os_version: Mapped[str | None] = mapped_column(String(160))
    app_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[BindingStatus] = mapped_column(
        Enum(
            BindingStatus,
            name="binding_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=BindingStatus.ACTIVE,
        index=True,
    )
    first_activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivate_reason: Mapped[str | None] = mapped_column(Text)
    last_ip: Mapped[str | None] = mapped_column(INET)
    device_credential_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    license = relationship("License", back_populates="bindings", lazy="raise")
    events = relationship("LicenseEvent", back_populates="binding", lazy="raise")
