"""create telephony.calls table

Revision ID: 0032_telephony_calls
Revises: 0031_telephony_routing_targets
Create Date: 2026-09-20 00:00:02.000000

docs/ROADMAP.md Phase 8.2. Ordinary RLS-scoped table. `contact_id` is a
composite FK into `crm.contacts`, column-scoped `ON DELETE SET NULL
(contact_id)` -- the identical fix `appointments.appointments.contact_id`
already applies for the defect class the deferred Phase 4 CRM bug
demonstrated (a bare, non-column-scoped `SET NULL` on a multi-column FK
nulls every column, including the `NOT NULL` `tenant_id`).
`phone_number_id` has no `ON DELETE` behavior decided (default
`RESTRICT`) -- see `product/telephony/models.py`'s own module docstring
for the disclosed open question this leaves.

**The partial unique index `uq_telephony_calls_tenant_provider_call`**
(`tenant_id`, `provider_name`, `provider_call_id`, `WHERE provider_call_id
IS NOT NULL`) is the real database-enforced guard against creating two
`Call` rows for the same provider-side call -- `product/telephony/calls.py
::receive_inbound_call_event()`/`initiate_outbound_call()` attempt the
insert and translate the resulting `IntegrityError` into an idempotent
re-fetch, never a "check then insert" as their own guarantee (mirrors
`appointments.appointments`'s own `EXCLUDE` constraint discipline, a
`UNIQUE` index rather than `EXCLUDE` since this is exact-match dedup, not
overlap detection). Partial (`WHERE ... IS NOT NULL`) because
`provider_call_id` is unknown until a provider has actually assigned one
-- many `NULL`s must not collide under uniqueness.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0032_telephony_calls"
down_revision: str | Sequence[str] | None = "0031_telephony_routing_targets"
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
        "calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("phone_number_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_call_id", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("from_number", sa.String(length=32), nullable=False),
        sa.Column("to_number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ringing"),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_telephony_calls_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "phone_number_id"],
            ["telephony.phone_numbers.tenant_id", "telephony.phone_numbers.id"],
            name="fk_telephony_calls_tenant_phone_number",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_telephony_calls_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')", name="ck_telephony_calls_direction"
        ),
        sa.CheckConstraint(
            "status IN ('ringing', 'in_progress', 'completed', 'no_answer', 'failed')",
            name="ck_telephony_calls_status",
        ),
        schema="telephony",
    )
    op.create_index("ix_telephony_calls_tenant_id", "calls", ["tenant_id"], schema="telephony")
    op.create_index(
        "ix_telephony_calls_phone_number_id", "calls", ["phone_number_id"], schema="telephony"
    )
    op.create_index("ix_telephony_calls_contact_id", "calls", ["contact_id"], schema="telephony")
    op.create_index(
        "ix_telephony_calls_assigned_user_id", "calls", ["assigned_user_id"], schema="telephony"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_telephony_calls_tenant_provider_call "
        "ON telephony.calls (tenant_id, provider_name, provider_call_id) "
        "WHERE provider_call_id IS NOT NULL"
    )

    for statement in tenant_rls_statements("calls", schema="telephony"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.calls TO "{_app_role()}"')


def downgrade() -> None:
    op.drop_table("calls", schema="telephony")
