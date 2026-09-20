"""create telephony.phone_number_routing_targets table

Revision ID: 0031_telephony_routing_targets
Revises: 0030_telephony_phone_numbers
Create Date: 2026-09-20 00:00:01.000000

docs/ROADMAP.md Phase 8.2. Ordinary RLS-scoped table -- reached only after
`telephony.phone_numbers` lookup has already established `tenant_id` (see
`product/telephony/models.py`'s own module docstring). `ON DELETE CASCADE`
on `phone_number_id`: a routing target has no meaning without its phone
number. `UniqueConstraint(tenant_id, phone_number_id, position)` and
`UniqueConstraint(tenant_id, phone_number_id, user_id)` together prevent
both a duplicate position and the same user appearing twice in one
number's routing list -- see `product/telephony/routing.py`'s own module
docstring for how `position` orders the round-robin tie-break.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0031_telephony_routing_targets"
down_revision: str | Sequence[str] | None = "0030_telephony_phone_numbers"
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
        "phone_number_routing_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("phone_number_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_telephony_routing_targets_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "phone_number_id",
            "position",
            name="uq_telephony_routing_targets_tenant_number_position",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "phone_number_id",
            "user_id",
            name="uq_telephony_routing_targets_tenant_number_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "phone_number_id"],
            ["telephony.phone_numbers.tenant_id", "telephony.phone_numbers.id"],
            name="fk_telephony_routing_targets_tenant_phone_number",
            ondelete="CASCADE",
        ),
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_routing_targets_tenant_id",
        "phone_number_routing_targets",
        ["tenant_id"],
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_routing_targets_phone_number_id",
        "phone_number_routing_targets",
        ["phone_number_id"],
        schema="telephony",
    )

    for statement in tenant_rls_statements("phone_number_routing_targets", schema="telephony"):
        op.execute(statement)

    app_role = _app_role()
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.phone_number_routing_targets "
        f'TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("phone_number_routing_targets", schema="telephony")
