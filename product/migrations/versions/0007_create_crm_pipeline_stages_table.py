"""create crm.pipeline_stages table

Revision ID: 0007_crm_pipeline_stages
Revises: 0006_crm_pipelines
Create Date: 2026-09-20 00:00:03.000000

docs/ROADMAP.md Phase 4.2. `pipeline_id` is a composite FK into
`crm.pipelines` (no ON DELETE clause -- RESTRICT, the default; this
phase ships no pipeline DELETE endpoint, see product/crm/pipelines.py's
own docstring). `ck_crm_pipeline_stages_not_won_and_lost` -- a stage
must never be both a won and a lost terminal stage at once.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0007_crm_pipeline_stages"
down_revision: str | Sequence[str] | None = "0006_crm_pipelines"
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
        "pipeline_stages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_lost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_pipeline_stages_tenant_id_id"),
        sa.UniqueConstraint(
            "pipeline_id", "position", name="uq_crm_pipeline_stages_pipeline_position"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"],
            ["crm.pipelines.tenant_id", "crm.pipelines.id"],
            name="fk_crm_pipeline_stages_tenant_pipeline",
        ),
        sa.CheckConstraint(
            "NOT (is_won AND is_lost)", name="ck_crm_pipeline_stages_not_won_and_lost"
        ),
        schema="crm",
    )
    op.create_index(
        "ix_crm_pipeline_stages_tenant_id", "pipeline_stages", ["tenant_id"], schema="crm"
    )

    for statement in tenant_rls_statements("pipeline_stages", schema="crm"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.pipeline_stages TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("pipeline_stages", schema="crm")
