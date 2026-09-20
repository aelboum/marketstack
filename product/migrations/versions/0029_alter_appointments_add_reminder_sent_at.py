"""add reminder_sent_at to appointments.appointments

Revision ID: 0029_appointments_reminder_at
Revises: 0028_appointments_manage_tokens
Create Date: 2026-09-20 00:00:05.000000

docs/ROADMAP.md Phase 7.3. Plain nullable `timestamptz` column on an
already-RLS-scoped, already-composite-FK'd table -- no new table, no new
foreign key, no RLS change (RLS policies are defined on the table, not
per-column). `NULL` means "no reminder sent yet"; non-NULL is the UTC
instant `product/appointments/reminders.py::send_due_reminders()` sent it,
written only after the outbound email actually succeeds (see that
module's own docstring on why this can never be set optimistically
before the send).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_appointments_reminder_at"  # <=32 chars: alembic_version.version_num's limit
down_revision: str | Sequence[str] | None = "0028_appointments_manage_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        schema="appointments",
    )
    # Supports send_due_reminders()'s own sweep predicate
    # (status = 'confirmed' AND reminder_sent_at IS NULL AND starts_at
    # BETWEEN now AND now + REMINDER_LEAD_TIME) -- a partial index would
    # need a literal `now()` bound it can't have, so this is a plain
    # composite index across the three filtered/ordered columns rather
    # than a partial one.
    op.create_index(
        "ix_appointments_appointments_reminder_sweep",
        "appointments",
        ["status", "reminder_sent_at", "starts_at"],
        schema="appointments",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_appointments_appointments_reminder_sweep",
        table_name="appointments",
        schema="appointments",
    )
    op.drop_column("appointments", "reminder_sent_at", schema="appointments")
