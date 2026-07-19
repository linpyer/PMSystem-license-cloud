"""Add audited trial reset, extension, and logical deletion.

Revision ID: 0006_trial_management_actions
Revises: 0005_trial_event_type_width
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_trial_management_actions"
down_revision: str | None = "0005_trial_event_type_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EVENTS_WITH_TRIAL_MANAGEMENT = (
    "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
    "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
    "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_ENABLED','LICENSE_REVOKED',"
    "'ADMIN_DEACTIVATED','LICENSE_EXPIRED','ABNORMAL_REQUEST','TRIAL_ACTIVATED',"
    "'TRIAL_REACTIVATED_SAME_DEVICE','TRIAL_VERIFIED','TRIAL_EXPIRED','TRIAL_CONVERTED',"
    "'TRIAL_DISABLED','TRIAL_ACTIVATION_FAILED','TRIAL_RECORDING_BLOCKED','TRIAL_RESET',"
    "'TRIAL_EXTENDED','TRIAL_DELETED','TRIAL_REACTIVATED_AFTER_DELETE')"
)

_EVENTS_BEFORE_TRIAL_MANAGEMENT = (
    "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
    "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
    "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_ENABLED','LICENSE_REVOKED',"
    "'ADMIN_DEACTIVATED','LICENSE_EXPIRED','ABNORMAL_REQUEST','TRIAL_ACTIVATED',"
    "'TRIAL_REACTIVATED_SAME_DEVICE','TRIAL_VERIFIED','TRIAL_EXPIRED','TRIAL_CONVERTED',"
    "'TRIAL_DISABLED','TRIAL_ACTIVATION_FAILED','TRIAL_RECORDING_BLOCKED')"
)


def _drop_legacy_check_constraint(*names: str) -> None:
    existing = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("device_trials")
    }
    for name in names:
        if name in existing:
            op.drop_constraint(op.f(name), "device_trials", type_="check")
            return
    raise RuntimeError(
        "Expected device_trials check constraint was not found: " + ", ".join(names)
    )


def upgrade() -> None:
    op.drop_constraint("uq_device_trials_device_fingerprint", "device_trials", type_="unique")
    _drop_legacy_check_constraint(
        "ck_device_trials_ck_device_trials_exact_168_hours",
        "ck_device_trials_exact_168_hours",
    )
    _drop_legacy_check_constraint(
        "ck_device_trials_ck_device_trials_device_trial_status",
        "ck_device_trials_device_trial_status",
    )

    op.add_column(
        "device_trials",
        sa.Column("reset_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("device_trials", sa.Column("last_reset_at", sa.DateTime(timezone=True)))
    op.add_column("device_trials", sa.Column("last_reset_by", postgresql.UUID(as_uuid=True)))
    op.add_column("device_trials", sa.Column("last_reset_reason", sa.Text()))
    op.add_column(
        "device_trials",
        sa.Column("extension_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "device_trials",
        sa.Column("total_extended_days", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("device_trials", sa.Column("last_extended_at", sa.DateTime(timezone=True)))
    op.add_column("device_trials", sa.Column("last_extended_by", postgresql.UUID(as_uuid=True)))
    op.add_column("device_trials", sa.Column("last_extension_days", sa.Integer()))
    op.add_column("device_trials", sa.Column("last_extension_reason", sa.Text()))
    op.add_column("device_trials", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("device_trials", sa.Column("deleted_by", postgresql.UUID(as_uuid=True)))
    op.add_column("device_trials", sa.Column("delete_reason", sa.Text()))

    op.create_foreign_key(
        "fk_device_trials_last_reset_by_admin_users",
        "device_trials",
        "admin_users",
        ["last_reset_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_device_trials_last_extended_by_admin_users",
        "device_trials",
        "admin_users",
        ["last_extended_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_device_trials_deleted_by_admin_users",
        "device_trials",
        "admin_users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "device_trial_status",
        "device_trials",
        "status IN ('ACTIVE','EXPIRED','CONVERTED','DISABLED','DELETED')",
    )
    op.create_check_constraint(
        "valid_time_range", "device_trials", "expires_at > started_at"
    )
    op.create_index(
        "uq_device_trials_active_device_fingerprint",
        "device_trials",
        ["device_id", "fingerprint_version"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_device_trials_deleted_at", "device_trials", ["deleted_at"])

    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type", "license_events", _EVENTS_WITH_TRIAL_MANAGEMENT
    )


def downgrade() -> None:
    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type", "license_events", _EVENTS_BEFORE_TRIAL_MANAGEMENT
    )
    op.drop_index("ix_device_trials_deleted_at", table_name="device_trials")
    op.drop_index("uq_device_trials_active_device_fingerprint", table_name="device_trials")
    op.drop_constraint(op.f("ck_device_trials_valid_time_range"), "device_trials", type_="check")
    op.drop_constraint(op.f("ck_device_trials_device_trial_status"), "device_trials", type_="check")
    op.create_check_constraint(
        "device_trial_status",
        "device_trials",
        "status IN ('ACTIVE','EXPIRED','CONVERTED','DISABLED')",
    )
    op.create_check_constraint(
        "exact_168_hours",
        "device_trials",
        "expires_at = started_at + INTERVAL '168 hours'",
    )
    for constraint_name in (
        "fk_device_trials_deleted_by_admin_users",
        "fk_device_trials_last_extended_by_admin_users",
        "fk_device_trials_last_reset_by_admin_users",
    ):
        op.drop_constraint(constraint_name, "device_trials", type_="foreignkey")
    for column_name in (
        "delete_reason",
        "deleted_by",
        "deleted_at",
        "last_extension_reason",
        "last_extension_days",
        "last_extended_by",
        "last_extended_at",
        "total_extended_days",
        "extension_count",
        "last_reset_reason",
        "last_reset_by",
        "last_reset_at",
        "reset_count",
    ):
        op.drop_column("device_trials", column_name)
    op.create_unique_constraint(
        "uq_device_trials_device_fingerprint",
        "device_trials",
        ["device_id", "fingerprint_version"],
    )
