"""create appointments.availability_rules table

Revision ID: 0025_appointments_avail_rules
Revises: 0024_appointments_calendars
Create Date: 2026-09-20 00:00:01.000000

docs/ROADMAP.md Phase 7.1. `start_time`/`end_time` are local wall-clock
minutes-since-midnight (0-1439 start, up to 1440 end) in the owning
calendar's own `timezone` -- see `product/appointments/models.py`'s own
module docstring for the full "instant vs. local time" reasoning.
`calendar_id` is `ON DELETE CASCADE` -- a rule has no meaning without its
calendar.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0025_appointments_avail_rules"
down_revision: str | Sequence[str] | None = "0024_appointments_calendars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Integer(), nullable=False),
        sa.Column("end_time", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_appointments_availability_rules_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_availability_rules_tenant_calendar",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_appointments_availability_rules_day_of_week",
        ),
        sa.CheckConstraint(
            "start_time >= 0 AND start_time < 1440",
            name="ck_appointments_availability_rules_start_time_bounds",
        ),
        sa.CheckConstraint(
            "end_time > 0 AND end_time <= 1440",
            name="ck_appointments_availability_rules_end_time_bounds",
        ),
        sa.CheckConstraint(
            "end_time > start_time",
            name="ck_appointments_availability_rules_end_after_start",
        ),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_availability_rules_tenant_id",
        "availability_rules",
        ["tenant_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_availability_rules_calendar_id",
        "availability_rules",
        ["calendar_id"],
        schema="appointments",
    )

    for statement in tenant_rls_statements("availability_rules", schema="appointments"):
        op.execute(statement)

    app_role = _app_role()
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.availability_rules TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("availability_rules", schema="appointments")
