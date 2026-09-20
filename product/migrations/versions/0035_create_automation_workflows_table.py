"""create automation.workflows table

Revision ID: 0035_automation_workflows
Revises: 0034_telephony_call_recordings
Create Date: 2026-09-20 00:00:00.000000

docs/ROADMAP.md Phase 10.2. First table in the `automation` schema --
creates the schema itself, mirroring `telephony.phone_numbers`'s own
0030 precedent. RLS via `infra.db.rls.tenant_rls_statements()`, identical
to every other tenant-owned table in this product.
`created_by_user_id` is a plain FK into the global `core.users` registry
(not composite -- `core.users` has no notion of tenant membership for a
composite FK to express); validated as a real reachable actor at the
service layer (`product/automation/workflows.py`), not by this FK alone.
See `product/automation/models.py`'s own module docstring for the full
reasoning behind every column choice.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0035_automation_workflows"
down_revision: str | Sequence[str] | None = "0034_telephony_call_recordings"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS automation")
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("action_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_automation_workflows_tenant_id_id"),
        schema="automation",
    )
    op.create_index(
        "ix_automation_workflows_tenant_id", "workflows", ["tenant_id"], schema="automation"
    )
    op.create_index(
        "ix_automation_workflows_trigger_type", "workflows", ["trigger_type"], schema="automation"
    )

    for statement in tenant_rls_statements("workflows", schema="automation"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA automation TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON automation.workflows TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA automation "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA automation "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("workflows", schema="automation")
    op.execute("DROP SCHEMA IF EXISTS automation")
