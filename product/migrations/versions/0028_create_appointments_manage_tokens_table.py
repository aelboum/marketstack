"""create appointments.appointment_manage_tokens table

Revision ID: 0028_appointments_manage_tokens
Revises: 0027_appointments_booking_links
Create Date: 2026-09-20 00:00:04.000000

docs/ROADMAP.md Phase 7.2. Deliberately NOT RLS-scoped, mirroring
`appointments.booking_links`'s own 0027 precedent (this migration)
exactly and for the identical reason: the public reschedule/cancel
endpoints must resolve `manage_token` -> `(tenant_id, appointment_id)`
before any tenant context exists. `(tenant_id, appointment_id)` carries
its own `UNIQUE` constraint -- one manage token per appointment.
`appointment_id` is `ON DELETE CASCADE` into `appointments.appointments`
(a manage token has no meaning without the appointment it manages).

See `product/appointments/models.py`'s own docstring on
`AppointmentManageToken` for the design-error-caught-and-corrected
history behind this being a separate table rather than a column on
`appointments.appointments`.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_appointments_manage_tokens"
down_revision: str | Sequence[str] | None = "0027_appointments_booking_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    app_role = _app_role()

    op.create_table(
        "appointment_manage_tokens",
        sa.Column("manage_token", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("manage_token", name="uq_appointments_manage_tokens_manage_token"),
        sa.UniqueConstraint(
            "tenant_id",
            "appointment_id",
            name="uq_appointments_manage_tokens_tenant_appointment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.appointments.tenant_id", "appointments.appointments.id"],
            name="fk_appointments_manage_tokens_tenant_appointment",
            ondelete="CASCADE",
        ),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_manage_tokens_tenant_id",
        "appointment_manage_tokens",
        ["tenant_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_manage_tokens_appointment_id",
        "appointment_manage_tokens",
        ["appointment_id"],
        schema="appointments",
    )

    # No tenant_rls_statements() call -- see module docstring.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.appointment_manage_tokens "
        f'TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("appointment_manage_tokens", schema="appointments")
