"""Expand license event names for trial audit events.

Revision ID: 0005_trial_event_type_width
Revises: 0004_device_trials
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_trial_event_type_width"
down_revision: str | None = "0004_device_trials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "license_events",
        "event_type",
        existing_type=sa.String(length=23),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "license_events",
        "event_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=23),
        existing_nullable=False,
    )
