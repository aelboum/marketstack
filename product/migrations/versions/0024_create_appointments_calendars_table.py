"""create appointments.calendars table

Revision ID: 0024_appointments_calendars
Revises: 0023_marketing_tracking
Create Date: 2026-09-20 00:00:00.000000

docs/ROADMAP.md Phase 7.1. First table in the `appointments` schema --
creates the schema itself, mirroring `crm.companies`'s own 0004
precedent: the migration that creates the schema is also the one whose
downgrade drops it, since it necessarily runs last in a full downgrade
chain. RLS via `infra.db.rls.tenant_rls_statements()`, identical to every
other tenant-owned table in this product. `owner_user_id` is a plain FK
into the global `core.users` registry (not composite -- `core.users` has
no notion of tenant membership for a composite FK to express); it is
validated as a real `TenantMembership` in `tenant_id` at the service
layer (`product/appointments/calendars.py`), not by this FK alone. See
`product/appointments/models.py`'s own module docstring for the full
reasoning behind every choice in this table.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0024_appointments_calendars"
down_revision: str | Sequence[str] | None = "0023_marketing_tracking"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS appointments")
    op.create_table(
        "calendars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_appointments_calendars_tenant_id_id"),
        schema="appointments",
    )
    op.create_index(
        "ix_appointments_calendars_tenant_id", "calendars", ["tenant_id"], schema="appointments"
    )

    for statement in tenant_rls_statements("calendars", schema="appointments"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA appointments TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON appointments.calendars TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA appointments "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA appointments "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("calendars", schema="appointments")
    op.execute("DROP SCHEMA IF EXISTS appointments")
