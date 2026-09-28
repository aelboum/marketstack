"""create accounting.periods table

Revision ID: 0053_accounting_periods
Revises: 0052_accounting_accounts
Create Date: 2026-09-27 00:00:01.000000

docs/ROADMAP.md Phase 24, ADR-0014 Decision 5. Mirrors
`product/appointments/models.py`'s own "double-booking prevention
constraint" mechanics exactly, adapted from calendar/time-range overlap
to tenant/date-range overlap:

1. `btree_gist` is **not** created here -- already installed by migration
   `0026_create_appointments_appointments_table` and deliberately left
   installed on every downgrade since (that migration's own module
   docstring: "database-global infrastructure, not something this
   migration privately owns"). This migration adds no second
   `CREATE EXTENSION`.
2. A generated, stored `period_range daterange` column
   (`GENERATED ALWAYS AS (daterange((start_date AT TIME ZONE 'UTC')::date,
   (end_date AT TIME ZONE 'UTC')::date, '[]')) STORED`) -- `start_date`/
   `end_date` are themselves `DateTime(timezone=True)` at the ORM level
   (`infra.db` exports no `Date` type, `product/accounting/models.py`'s
   own module docstring), stored at UTC midnight; the `AT TIME ZONE
   'UTC'` conversion (a *fixed*-offset zone, so Postgres accepts it as
   `IMMUTABLE` -- a plain `::date` cast on a `timestamptz` is rejected
   here with "generation expression is not immutable," since a bare cast
   depends on the session's own `TimeZone` setting) is what lets a real
   Postgres `daterange` (over `date`, not `timestamptz`) exist over them.
   `'[]'` is inclusive on both ends, per Decision 5's own stated range
   convention -- deliberately different from `Appointment.time_range`'s
   `'[)'`, because a period's own end date is itself the last day
   included, not an exclusive boundary.
3. `EXCLUDE USING gist (tenant_id WITH =, period_range WITH &&)` -- no
   partial `WHERE` predicate, unlike `Appointment`'s own constraint: a
   `closed` period's date range is never freed for a new period to reuse
   (Decision 5's own "closing a period does not retroactively invalidate
   anything," extended here to "does not free its date range either" --
   a period's own identity is its date range, not merely its current
   status).

Ordinary RLS-scoped, tenant-owned data otherwise. `status` carries a real
`CheckConstraint`.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0053_accounting_periods"
down_revision: str | Sequence[str] | None = "0052_accounting_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"
_EXCLUDE_CONSTRAINT_NAME = "ex_accounting_periods_no_overlap_per_tenant"


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    app_role = _app_role()

    op.create_table(
        "periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_periods_tenant_id_id"),
        sa.CheckConstraint("end_date >= start_date", name="ck_accounting_periods_end_after_start"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_accounting_periods_status"),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_periods_tenant_id", "periods", ["tenant_id"], schema="accounting"
    )

    # Generated, stored range column -- see module docstring point 2.
    op.execute(
        "ALTER TABLE accounting.periods "
        "ADD COLUMN period_range daterange "
        "GENERATED ALWAYS AS (daterange("
        "(start_date AT TIME ZONE 'UTC')::date, (end_date AT TIME ZONE 'UTC')::date, '[]'"
        ")) STORED"
    )

    # The actual non-overlap enforcement -- see module docstring point 3.
    op.execute(
        "ALTER TABLE accounting.periods "
        f"ADD CONSTRAINT {_EXCLUDE_CONSTRAINT_NAME} "
        "EXCLUDE USING gist (tenant_id WITH =, period_range WITH &&)"
    )

    for statement in tenant_rls_statements("periods", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.periods TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("periods", schema="accounting")
