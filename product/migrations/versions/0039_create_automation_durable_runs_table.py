"""create automation.durable_runs table

Revision ID: 0039_durable_runs
Revises: 0038_durable_workflow_versions
Create Date: 2026-09-20 00:00:04.000000

docs/ROADMAP.md Phase 10.3. Business execution state -- never a mirror
of Temporal's own execution history (`product/automation/durable
/models.py`'s own module docstring). `UniqueConstraint(tenant_id,
workflow_id, trigger_dedup_key)` is the idempotency/reservation
backbone, identical discipline to `automation.workflow_runs` (0036) and
`telephony.call_events`, extended here to also dedupe manually-started
runs via a caller-supplied (or freshly generated) idempotency key
(`product/automation/durable/runs.py::start_run()`'s own module
docstring). `UniqueConstraint(tenant_id, temporal_workflow_id)` --
each run maps to exactly one Temporal execution, never shared.
`ON DELETE CASCADE` on `workflow_id`; a *plain* (non-cascading) FK on
`workflow_version_id` -- a version must never be deletable while a run
still references it (this phase's own "deleting/archiving a workflow
must not invalidate historical runs" requirement; versions are never
deleted by any code path in this product, only workflows/runs are, via
`product/automation/purge.py`'s own tenant-purge participant, which
deletes runs before versions -- see that module's own `_PURGE_ORDER`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0039_durable_runs"
down_revision: str | Sequence[str] | None = "0038_durable_workflow_versions"
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
        "durable_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("trigger_dedup_key", sa.String(length=255), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=True),
        sa.Column("temporal_run_id", sa.String(length=255), nullable=True),
        sa.Column("current_step_key", sa.String(length=64), nullable=True),
        sa.Column("waiting_for_event_type", sa.String(length=64), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_automation_durable_runs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "trigger_dedup_key",
            name="uq_automation_durable_runs_tenant_workflow_dedup",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "temporal_workflow_id",
            name="uq_automation_durable_runs_temporal_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.durable_workflows.tenant_id", "automation.durable_workflows.id"],
            name="fk_automation_durable_runs_tenant_workflow",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            [
                "automation.durable_workflow_versions.tenant_id",
                "automation.durable_workflow_versions.id",
            ],
            name="fk_automation_durable_runs_tenant_workflow_version",
        ),
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_runs_tenant_id", "durable_runs", ["tenant_id"], schema="automation"
    )
    op.create_index(
        "ix_automation_durable_runs_workflow_id",
        "durable_runs",
        ["workflow_id"],
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_runs_status", "durable_runs", ["status"], schema="automation"
    )

    for statement in tenant_rls_statements("durable_runs", schema="automation"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON automation.durable_runs TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("durable_runs", schema="automation")
