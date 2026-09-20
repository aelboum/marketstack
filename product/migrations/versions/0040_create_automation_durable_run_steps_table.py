"""create automation.durable_run_steps table

Revision ID: 0040_durable_run_steps
Revises: 0039_durable_runs
Create Date: 2026-09-20 00:00:05.000000

docs/ROADMAP.md Phase 10.3. The business-level, per-step outcome ledger
this phase's own "step execution state" requirement and "step
started"/"step completed"/"step failed" audit events are built on --
never a mirror of Temporal's own replay history: no retry-attempt
count, no serialized activity input/output, no timer state
(`product/automation/durable/models.py`'s own module docstring).
`ON DELETE CASCADE` on `run_id` -- a step record has no meaning without
its parent run.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0040_durable_run_steps"
down_revision: str | Sequence[str] | None = "0039_durable_runs"
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
        "durable_run_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_automation_durable_run_steps_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["automation.durable_runs.tenant_id", "automation.durable_runs.id"],
            name="fk_automation_durable_run_steps_tenant_run",
            ondelete="CASCADE",
        ),
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_run_steps_tenant_id",
        "durable_run_steps",
        ["tenant_id"],
        schema="automation",
    )
    op.create_index(
        "ix_automation_durable_run_steps_run_id",
        "durable_run_steps",
        ["run_id"],
        schema="automation",
    )

    for statement in tenant_rls_statements("durable_run_steps", schema="automation"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON automation.durable_run_steps TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("durable_run_steps", schema="automation")
