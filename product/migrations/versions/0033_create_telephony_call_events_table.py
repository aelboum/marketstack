"""create telephony.call_events table

Revision ID: 0033_telephony_call_events
Revises: 0032_telephony_calls
Create Date: 2026-09-20 00:00:03.000000

docs/ROADMAP.md Phase 8.2. **The real idempotency/replay-protection
ledger for inbound provider events** -- `UniqueConstraint(tenant_id,
provider_name, provider_event_id)` is what actually makes double-
processing of the same provider event impossible;
`product/telephony/calls.py::receive_inbound_call_event()` performs the
insert and translates the resulting `IntegrityError` into a no-op, never
a "check then insert" as its own guarantee. `ON DELETE CASCADE` on
`call_id` -- an event has no meaning without its parent call.

Carries no raw provider-payload column -- see
`product/telephony/models.py::CallEvent`'s own docstring: `event_type` +
these identifiers are enough to dedupe and know what happened; an
arbitrary provider payload is exactly the kind of unbounded, potentially
PII-carrying blob this phase's own audit/PII discipline says not to
persist without a proven need.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0033_telephony_call_events"
down_revision: str | Sequence[str] | None = "0032_telephony_calls"
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
        "call_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_telephony_call_events_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_name",
            "provider_event_id",
            name="uq_telephony_call_events_tenant_provider_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["telephony.calls.tenant_id", "telephony.calls.id"],
            name="fk_telephony_call_events_tenant_call",
            ondelete="CASCADE",
        ),
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_call_events_tenant_id", "call_events", ["tenant_id"], schema="telephony"
    )
    op.create_index(
        "ix_telephony_call_events_call_id", "call_events", ["call_id"], schema="telephony"
    )

    for statement in tenant_rls_statements("call_events", schema="telephony"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.call_events TO "{_app_role()}"')


def downgrade() -> None:
    op.drop_table("call_events", schema="telephony")
