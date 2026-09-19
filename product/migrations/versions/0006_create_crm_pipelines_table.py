"""create crm.pipelines table

Revision ID: 0006_crm_pipelines
Revises: 0005_crm_contacts
Create Date: 2026-09-20 00:00:02.000000

docs/ROADMAP.md Phase 4.2.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0006_crm_pipelines"
down_revision: str | Sequence[str] | None = "0005_crm_contacts"
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
        "pipelines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_pipelines_tenant_id_id"),
        schema="crm",
    )
    op.create_index("ix_crm_pipelines_tenant_id", "pipelines", ["tenant_id"], schema="crm")

    for statement in tenant_rls_statements("pipelines", schema="crm"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.pipelines TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("pipelines", schema="crm")
