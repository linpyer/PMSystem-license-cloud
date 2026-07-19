"""Add one-time device trials.

Revision ID: 0004_device_trials
Revises: 0003_signing_key_rotation
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_device_trials"
down_revision: str | None = "0003_signing_key_rotation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("license_type", "licenses", type_="check")
    op.create_check_constraint(
        "license_type",
        "licenses",
        "license_type IN ('TRIAL','monthly','yearly','permanent','fixed_date')",
    )
    op.alter_column("licenses", "license_code_hash", existing_type=sa.String(64), nullable=True)
    op.alter_column("licenses", "license_code_masked", existing_type=sa.String(32), nullable=True)
    op.create_check_constraint(
        "license_code_presence",
        "licenses",
        "(license_type = 'TRIAL' AND license_code_hash IS NULL AND license_code_masked IS NULL) "
        "OR (license_type <> 'TRIAL' AND license_code_hash IS NOT NULL AND license_code_masked IS NOT NULL)",
    )

    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type",
        "license_events",
        "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
        "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
        "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_ENABLED','LICENSE_REVOKED',"
        "'ADMIN_DEACTIVATED','LICENSE_EXPIRED','ABNORMAL_REQUEST','TRIAL_ACTIVATED',"
        "'TRIAL_REACTIVATED_SAME_DEVICE','TRIAL_VERIFIED','TRIAL_EXPIRED','TRIAL_CONVERTED',"
        "'TRIAL_DISABLED','TRIAL_ACTIVATION_FAILED','TRIAL_RECORDING_BLOCKED')",
    )

    op.create_table(
        "device_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.String(length=200), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=40), nullable=False),
        sa.Column("trial_license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_license_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_ip", postgresql.INET(), nullable=True),
        sa.Column("last_ip", postgresql.INET(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_name", sa.String(length=200), nullable=True),
        sa.Column("os_version", sa.String(length=160), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','EXPIRED','CONVERTED','DISABLED')",
            name="ck_device_trials_device_trial_status",
        ),
        sa.CheckConstraint(
            "expires_at = started_at + INTERVAL '168 hours'",
            name="ck_device_trials_exact_168_hours",
        ),
        sa.ForeignKeyConstraint(
            ["trial_license_id"], ["licenses.id"],
            name="fk_device_trials_trial_license_id_licenses", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["converted_license_id"], ["licenses.id"],
            name="fk_device_trials_converted_license_id_licenses", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_trials"),
        sa.UniqueConstraint(
            "device_id", "fingerprint_version", name="uq_device_trials_device_fingerprint"
        ),
        sa.UniqueConstraint("trial_license_id", name="uq_device_trials_trial_license_id"),
    )
    op.create_index("ix_device_trials_status", "device_trials", ["status"])
    op.create_index("ix_device_trials_expires_at", "device_trials", ["expires_at"])
    op.create_index("ix_device_trials_last_seen_at", "device_trials", ["last_seen_at"])


def downgrade() -> None:
    op.drop_table("device_trials")
    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type", "license_events",
        "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
        "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
        "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_ENABLED','LICENSE_REVOKED',"
        "'ADMIN_DEACTIVATED','LICENSE_EXPIRED','ABNORMAL_REQUEST')",
    )
    op.drop_constraint("license_code_presence", "licenses", type_="check")
    op.alter_column("licenses", "license_code_masked", existing_type=sa.String(32), nullable=False)
    op.alter_column("licenses", "license_code_hash", existing_type=sa.String(64), nullable=False)
    op.drop_constraint("license_type", "licenses", type_="check")
    op.create_check_constraint(
        "license_type", "licenses",
        "license_type IN ('monthly','yearly','permanent','fixed_date')",
    )
