"""create appointments.booking_links table

Revision ID: 0027_appointments_booking_links
Revises: 0026_appointments_appointments
Create Date: 2026-09-20 00:00:03.000000

docs/ROADMAP.md Phase 7.2. Deliberately NOT RLS-scoped, mirroring
`marketing.forms`'s own 0020 precedent exactly: the whole point of a
`link_token` is resolving `(tenant_id, calendar_id)` *from* the token,
before any tenant context exists -- an RLS policy keyed on a not-yet-known
`app.tenant_id` would make that resolution impossible. `link_token`
carries a real, standalone `UNIQUE` constraint (global, not composite
with `tenant_id`). `(tenant_id, calendar_id)` also carries its own
`UNIQUE` constraint -- one booking link per calendar (1:1); see
`product/appointments/models.py::BookingLink`'s own docstring for the
scope-simplification this narrows to (a multi-calendar "book with any
available staff" selector is a disclosed, deferred extension).

See `product/appointments/models.py`'s own docstring on `BookingLink` for
the design-error-caught-and-corrected history behind this being a
separate table rather than a column on `appointments.calendars`.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_appointments_booking_links"
down_revision: str | Sequence[str] | None = "0026_appointments_appointments"
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
        "booking_links",
        sa.Column("link_token", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("link_token", name="uq_appointments_booking_links_link_token"),
        sa.UniqueConstraint(
            "tenant_id", "calendar_id", name="uq_appointments_booking_links_tenant_calendar"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_booking_links_tenant_calendar",
            ondelete="CASCADE",
        ),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_booking_links_tenant_id",
        "booking_links",
        ["tenant_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_booking_links_calendar_id",
        "booking_links",
        ["calendar_id"],
        schema="appointments",
    )

    # No tenant_rls_statements() call -- see module docstring.
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.booking_links TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("booking_links", schema="appointments")
