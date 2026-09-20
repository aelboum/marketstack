"""create automation.durable_workflows table

Revision ID: 0037_durable_workflows
Revises: 0036_automation_workflow_runs
Create Date: 2026-09-20 00:00:02.000000

docs/ROADMAP.md Phase 10.3. The stable identity for a multi-step durable
workflow -- see `product/automation/durable/models.py`'s own module
docstring for the full versioned-immutable-once-published design this
table anchors. `current_published_version_id` is deliberately not a
composite FK against `durable_workflow_versions` (that table's own
0038 migration composite-FKs back to this one -- a circular table
dependency would result); validated at the service layer
(`product/automation/durable/definitions.py::publish_version()`)
instead, mirroring `automation.workflows.created_by_user_id`'s own
"validated at the service layer, not by the FK alone" precedent
(0035's own migration).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0037_durable_workflows"
down_revision: str | Sequence[str] | None = "0036_automation_workflow_runs"
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
        "durable_workflows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_automation_durable_workflows_tenant_id_id"),
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_workflows_tenant_id",
        "durable_workflows",
        ["tenant_id"],
        schema="automation",
    )

    for statement in tenant_rls_statements("durable_workflows", schema="automation"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON automation.durable_workflows TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("durable_workflows", schema="automation")
