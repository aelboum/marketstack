"""create appointments.appointments table

Revision ID: 0026_appointments_appointments
Revises: 0025_appointments_avail_rules
Create Date: 2026-09-20 00:00:02.000000

docs/ROADMAP.md Phase 7.2. **The safety-critical migration of this
phase** -- see `product/appointments/models.py`'s own module docstring
("The double-booking prevention constraint") for the full mechanics this
migration implements:

1. `CREATE EXTENSION IF NOT EXISTS btree_gist` -- required for a GiST
   index/exclusion constraint to support plain equality (`=`) on the
   `uuid` `calendar_id` column; GiST alone only natively supports
   range/geometric operators.
2. A generated, stored `time_range tstzrange` column
   (`GENERATED ALWAYS AS (tstzrange(starts_at, ends_at, '[)')) STORED`)
   -- `[)` is inclusive-start/exclusive-end, the range convention that
   correctly allows two back-to-back appointments (10:00-10:30,
   10:30-11:00) on the same calendar without colliding. Added via raw
   `ALTER TABLE ... ADD COLUMN` (not `op.create_table`'s ordinary column
   list) because a `GENERATED ALWAYS AS` column has no equivalent in this
   product's `op.create_table(sa.Column(...))` vocabulary used elsewhere.
3. `EXCLUDE USING gist (calendar_id WITH =, time_range WITH &&) WHERE
   (status = 'confirmed')` -- the actual database-enforced double-booking
   prevention: two rows on the *same* `calendar_id` whose `time_range`s
   overlap (`&&`) cannot both exist while `status = 'confirmed'`. This is
   the real safety net; `product/appointments/booking.py::book_appointment()`
   /`public_reschedule_appointment()`/`staff_reschedule_appointment()`
   simply attempt the write and translate the resulting
   `IntegrityError`/`ExclusionViolation` into
   `AppointmentSlotUnavailableError` -- never a "check then insert" as
   the application's own guarantee. The partial `WHERE (status =
   'confirmed')` predicate is what lets a cancelled appointment's former
   slot be rebooked (a `'cancelled'` row's `time_range` is excluded from
   the constraint entirely).

`contact_id` is a composite FK into `crm.contacts`, column-scoped
`ON DELETE SET NULL (contact_id)` -- deleting a contact must not destroy
booking history, only unlink it (the fix for the defect class the
deferred Phase 4 CRM bug demonstrated: a bare, non-column-scoped
`SET NULL` on a multi-column FK nulls every column in the FK, including
the `NOT NULL` `tenant_id`). `calendar_id` has no `ON DELETE` behavior
decided (default `RESTRICT`) -- see `product/appointments/models.py`'s
own module docstring, "Deletion behavior", for the disclosed open
question this leaves for calendar deletion.

**`btree_gist` is left installed on downgrade**, deliberately: a
`CREATE EXTENSION` is database-global infrastructure, not something this
migration privately owns the way it owns its own schema/table -- the
same reasoning `crm.companies`'s own 0004 migration applies to *not*
dropping `core`/other schemas it depends on, applied here to an
extension instead of a schema.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0026_appointments_appointments"
down_revision: str | Sequence[str] | None = "0025_appointments_avail_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"
_EXCLUDE_CONSTRAINT_NAME = "ex_appointments_appointments_no_overlap_confirmed"


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    app_role = _app_role()

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="confirmed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_appointments_appointments_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_appointments_tenant_calendar",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_appointments_appointments_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at", name="ck_appointments_appointments_ends_after_starts"
        ),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_appointments_tenant_id",
        "appointments",
        ["tenant_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_appointments_calendar_id",
        "appointments",
        ["calendar_id"],
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_appointments_contact_id",
        "appointments",
        ["contact_id"],
        schema="appointments",
    )

    # Generated, stored range column -- see module docstring point 2.
    op.execute(
        "ALTER TABLE appointments.appointments "
        "ADD COLUMN time_range tstzrange "
        "GENERATED ALWAYS AS (tstzrange(starts_at, ends_at, '[)')) STORED"
    )

    # The actual double-booking prevention -- see module docstring point 3.
    op.execute(
        "ALTER TABLE appointments.appointments "
        f"ADD CONSTRAINT {_EXCLUDE_CONSTRAINT_NAME} "
        "EXCLUDE USING gist (calendar_id WITH =, time_range WITH &&) "
        "WHERE (status = 'confirmed')"
    )

    for statement in tenant_rls_statements("appointments", schema="appointments"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.appointments TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("appointments", schema="appointments")
    # btree_gist is deliberately left installed -- see module docstring.
