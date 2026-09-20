"""create automation.durable_workflow_versions table

Revision ID: 0038_durable_workflow_versions
Revises: 0037_durable_workflows
Create Date: 2026-09-20 00:00:03.000000

docs/ROADMAP.md Phase 10.3. `status` moves `draft -> published` exactly
once, enforced at the service layer
(`product/automation/durable/definitions.py::publish_version()`), never
mutated back -- `steps` (the full step graph, validated by
`product/automation/durable/dsl.py` before insert) is bounded JSON on
this row, not a separate table (`product/automation/durable/models.py`'s
own module docstring: "keeping the whole graph as one JSON value on the
version row is also what makes 'immutable once published' a single-row
guarantee"). `ON DELETE CASCADE` on `workflow_id` -- a version has no
meaning without its parent workflow.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0038_durable_workflow_versions"
down_revision: str | Sequence[str] | None = "0037_durable_workflows"
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
        "durable_workflow_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("trigger_type", sa.String(length=64), nullable=True),
        sa.Column("trigger_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("start_step_key", sa.String(length=64), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_automation_durable_workflow_versions_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "version_number",
            name="uq_automation_durable_workflow_versions_tenant_workflow_number",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.durable_workflows.tenant_id", "automation.durable_workflows.id"],
            name="fk_automation_durable_workflow_versions_tenant_workflow",
            ondelete="CASCADE",
        ),
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_workflow_versions_tenant_id",
        "durable_workflow_versions",
        ["tenant_id"],
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_workflow_versions_workflow_id",
        "durable_workflow_versions",
        ["workflow_id"],
        schema="automation",
    )

    for statement in tenant_rls_statements("durable_workflow_versions", schema="automation"):
        op.execute(statement)

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON automation.durable_workflow_versions "
        f'TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("durable_workflow_versions", schema="automation")
