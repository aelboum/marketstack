"""create automation.workflow_runs table

Revision ID: 0036_automation_workflow_runs
Revises: 0035_automation_workflows
Create Date: 2026-09-20 00:00:01.000000

docs/ROADMAP.md Phase 10.2. **The idempotency/audit ledger** --
`UniqueConstraint(tenant_id, workflow_id, trigger_dedup_key)` is the real,
database-enforced guard against double-executing the same logical trigger
occurrence for the same workflow, mirroring `telephony.call_events`'s own
`UniqueConstraint(tenant_id, provider_name, provider_event_id)` idempotency
backbone exactly (see `product/automation/models.py`'s own module
docstring for the full mechanics). `ON DELETE CASCADE` on `workflow_id`
-- a run record has no meaning without its parent workflow.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0036_automation_workflow_runs"
down_revision: str | Sequence[str] | None = "0035_automation_workflows"
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
        "workflow_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_dedup_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_automation_workflow_runs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "trigger_dedup_key",
            name="uq_automation_workflow_runs_tenant_workflow_dedup",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.workflows.tenant_id", "automation.workflows.id"],
            name="fk_automation_workflow_runs_tenant_workflow",
            ondelete="CASCADE",
        ),
        schema="automation",
    )
    op.create_index(
        "ix_automation_workflow_runs_tenant_id",
        "workflow_runs",
        ["tenant_id"],
        schema="automation",
    )
    op.create_index(
        "ix_automation_workflow_runs_workflow_id",
        "workflow_runs",
        ["workflow_id"],
        schema="automation",
    )

    for statement in tenant_rls_statements("workflow_runs", schema="automation"):
        op.execute(statement)

    app_role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON automation.workflow_runs TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("workflow_runs", schema="automation")
