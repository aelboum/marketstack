"""create telephony.phone_numbers table

Revision ID: 0030_telephony_phone_numbers
Revises: 0029_appointments_reminder_at
Create Date: 2026-09-20 00:00:00.000000

docs/ROADMAP.md Phase 8.1. First table in the `telephony` schema --
creates the schema itself, mirroring `appointments.calendars`'s own 0024
precedent: the migration that creates the schema is also the one whose
downgrade drops it.

**Deliberately NOT RLS-scoped**, mirroring `appointments.booking_links`'s
own 0027 precedent exactly: an inbound provider webhook's `to_number` is
the only signal available to resolve which tenant it belongs to, and that
resolution must happen *before* any tenant context exists -- an RLS
policy keyed on a not-yet-known `app.tenant_id` would make that
resolution structurally impossible. `phone_number` carries a real,
standalone `UNIQUE` constraint (global, not composite with `tenant_id`) --
a real phone number can only ever be provisioned to one tenant at a time.
`UniqueConstraint(tenant_id, id)` is still present (needed for composite
FKs from `calls`/`phone_number_routing_targets`) even without RLS -- RLS
is a Postgres policy layered on top of a table, structurally independent
of whether a composite-FK target unique index exists.

See `product/telephony/models.py`'s own module docstring for the full
reasoning behind every choice in this table.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_telephony_phone_numbers"
down_revision: str | Sequence[str] | None = "0029_appointments_reminder_at"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS telephony")
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_number_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_telephony_phone_numbers_tenant_id_id"),
        sa.UniqueConstraint("phone_number", name="uq_telephony_phone_numbers_phone_number"),
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_phone_numbers_tenant_id", "phone_numbers", ["tenant_id"], schema="telephony"
    )

    # No tenant_rls_statements() call -- see module docstring.
    op.execute(f'GRANT USAGE ON SCHEMA telephony TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.phone_numbers TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA telephony "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA telephony "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("phone_numbers", schema="telephony")
    op.execute("DROP SCHEMA IF EXISTS telephony")
