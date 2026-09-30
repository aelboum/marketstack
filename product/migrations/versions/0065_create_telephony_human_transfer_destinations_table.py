"""create telephony.human_transfer_destinations table

Revision ID: 0065_human_transfer_dest
Revises: 0064_telephony_transferring
Create Date: 2026-09-29 00:00:01.000000

docs/ROADMAP.md Phase 27.0. The approved human-destination decision: one
trusted, tenant-configured destination the AI receptionist's attended
transfer dials -- never selected by caller speech/DTMF, never by LLM/AI
tool output, never by a provider webhook parameter. Ordinary RLS-scoped
table (`product/telephony/models.py`'s own module docstring), reached only
through an already-authenticated, tenant-scoped service call
(`product/telephony/destinations.py`) -- never through the untenanted
`telephony.phone_numbers` lookup path `PhoneNumber` itself requires.

`UniqueConstraint(tenant_id)` enforces the approved "exactly one trusted
human destination per tenant" scope -- no ordered list, no queue, no
per-phone-number variant (docs/ROADMAP.md Phase 27.0's own "do not
introduce multiple destinations" instruction). `kind` is a closed,
CHECK-constrained vocabulary of exactly one value today (`'e164'`) --
`'sip_uri'` remains a documented future value the provider-neutral
`HumanDestination` domain type already anticipates
(`product/telephony/destinations.py`'s own module docstring), but is not
added to this constraint until a real SIP destination is actually
implemented (this phase's own "do not implement SIP URI handling now"
instruction).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0065_human_transfer_dest"
down_revision: str | Sequence[str] | None = "0064_telephony_transferring"
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
        "human_transfer_destinations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="e164"),
        sa.Column("e164_value", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_telephony_human_transfer_dest_tenant_id_id"
        ),
        sa.UniqueConstraint("tenant_id", name="uq_telephony_human_transfer_dest_tenant_id"),
        sa.CheckConstraint("kind IN ('e164')", name="ck_telephony_human_transfer_dest_kind"),
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_human_transfer_dest_tenant_id",
        "human_transfer_destinations",
        ["tenant_id"],
        schema="telephony",
    )

    for statement in tenant_rls_statements("human_transfer_destinations", schema="telephony"):
        op.execute(statement)

    app_role = _app_role()
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.human_transfer_destinations "
        f'TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("human_transfer_destinations", schema="telephony")
