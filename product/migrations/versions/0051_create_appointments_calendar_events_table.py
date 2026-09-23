"""create appointments.calendar_events table

Revision ID: 0051_appointments_cal_events
Revises: 0050_websites_lead_submissions
Create Date: 2026-09-23 00:00:00.000000

Calendar Foundation (docs/ROADMAP.md Phase 7.5). Introduces the generic
scheduling representation the Calendar Foundation needs, without touching
`appointments.appointments` at all: `product/appointments/models.py::
Appointment` remains the sole business-appointment model, unmodified by
this migration.

`calendar_id` mirrors `appointments.appointments.calendar_id` exactly --
no `ON DELETE` behavior decided (default `RESTRICT`), the same disclosed
open question `product/appointments/models.py`'s own module docstring
already carries for `Appointment.calendar_id` (this phase adds no new
calendar-delete-with-dependents handling).

`appointment_id` is nullable -- a `calendar_events` row is either a
generic event (`appointment_id IS NULL`, `title` required) or an
appointment-backed event (`appointment_id` set, `title` may be left to
the appointment/contact it backs). Column-scoped `ON DELETE SET NULL
(appointment_id)`, mirroring `appointments.appointments.contact_id`'s own
proven shape exactly (`product/appointments/models.py`'s module
docstring, "Deletion behavior") -- a purged/deleted appointment row must
not destroy the calendar event that represented it, only unlink it.

The "title required unless appointment-backed" rule is deliberately a
service-layer-only check (`product/appointments/calendar_events.py`), not
a DB `CHECK` constraint here -- see `product/appointments/models.py
::CalendarEvent`'s own docstring for why a `CHECK` would make the
`SET NULL` above fail instead of unlink for an untitled appointment-backed
row.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0051_appointments_cal_events"
down_revision: str | Sequence[str] | None = "0050_websites_lead_submissions"
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
        "calendar_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_appointments_calendar_events_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_calendar_events_tenant_calendar",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.appointments.tenant_id", "appointments.appointments.id"],
            name="fk_appointments_calendar_events_tenant_appointment",
            ondelete="SET NULL (appointment_id)",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at", name="ck_appointments_calendar_events_ends_after_starts"
        ),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_calendar_events_tenant_id",
        "calendar_events",
        ["tenant_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_calendar_events_calendar_id",
        "calendar_events",
        ["calendar_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_calendar_events_appointment_id",
        "calendar_events",
        ["appointment_id"],
        schema="appointments",
    )

    for statement in tenant_rls_statements("calendar_events", schema="appointments"):
        op.execute(statement)

    app_role = _app_role()
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.calendar_events TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("calendar_events", schema="appointments")
