from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import LicenseStatus, LicenseType


class License(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "licenses"
    __table_args__ = (
        CheckConstraint("max_devices >= 1", name="max_devices_positive"),
        CheckConstraint("valid_days IS NULL OR valid_days > 0", name="valid_days_positive"),
        CheckConstraint(
            "(license_type = 'TRIAL' AND license_code_hash IS NULL AND license_code_masked IS NULL) "
            "OR (license_type <> 'TRIAL' AND license_code_hash IS NOT NULL "
            "AND license_code_masked IS NOT NULL)",
            name="license_code_presence",
        ),
    )

    license_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    license_code_masked: Mapped[str | None] = mapped_column(String(32))
    license_type: Mapped[LicenseType] = mapped_column(
        Enum(
            LicenseType,
            name="license_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    status: Mapped[LicenseStatus] = mapped_column(
        Enum(
            LicenseStatus,
            name="license_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=LicenseStatus.CREATED,
        index=True,
    )
    valid_days: Mapped[int | None] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    max_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    customer_name: Mapped[str | None] = mapped_column(String(160))
    customer_contact: Mapped[str | None] = mapped_column(String(240))
    remark: Mapped[str | None] = mapped_column(Text)

    bindings = relationship("DeviceBinding", back_populates="license", lazy="raise")
    events = relationship("LicenseEvent", back_populates="license", lazy="raise")
    trial = relationship(
        "DeviceTrial", back_populates="trial_license", foreign_keys="DeviceTrial.trial_license_id",
        uselist=False, lazy="raise",
    )
