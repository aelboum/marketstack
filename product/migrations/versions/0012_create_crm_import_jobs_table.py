"""create crm.import_jobs table

Revision ID: 0012_crm_import_jobs
Revises: 0011_crm_tags
Create Date: 2026-09-20 00:00:08.000000

docs/ROADMAP.md Phase 4.5. Records a bulk CSV-import job's progress and
per-row outcome -- infra.jobs' own register_job() sets keep_result=0
(no arq-persisted result), so this table is the only place a caller can
poll "how did my import go" after enqueueing it. No FK to any other
crm.* table: an import job describes an operation, not a business record.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0012_crm_import_jobs"
down_revision: str | Sequence[str] | None = "0011_crm_tags"
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
        "import_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("succeeded_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_report", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_import_jobs_tenant_id_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_crm_import_jobs_status",
        ),
        schema="crm",
    )
    op.create_index("ix_crm_import_jobs_tenant_id", "import_jobs", ["tenant_id"], schema="crm")
    for statement in tenant_rls_statements("import_jobs", schema="crm"):
        op.execute(statement)
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.import_jobs TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("import_jobs", schema="crm")
