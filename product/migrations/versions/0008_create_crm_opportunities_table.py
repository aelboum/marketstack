"""create crm.opportunities table

Revision ID: 0008_crm_opportunities
Revises: 0007_crm_pipeline_stages
Create Date: 2026-09-20 00:00:04.000000

docs/ROADMAP.md Phase 4.2. `amount_minor_units`/`amount_currency`
mirror `product.foundation.values.Money` (integer minor units + a
3-letter currency code) -- converted at the service boundary
(product/crm/opportunities.py), never stored as a `Decimal`/`float`.
`contact_id`/`company_id` ON DELETE SET NULL (an opportunity survives
losing its contact/company link); `pipeline_id`/`stage_id` have no ON
DELETE clause (RESTRICT) since neither pipelines nor stages have a
DELETE endpoint in this phase.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0008_crm_opportunities"
down_revision: str | Sequence[str] | None = "0007_crm_pipeline_stages"
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
        "opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor_units", sa.Integer(), nullable=True),
        sa.Column("amount_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_opportunities_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_opportunities_tenant_contact",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_opportunities_tenant_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"],
            ["crm.pipelines.tenant_id", "crm.pipelines.id"],
            name="fk_crm_opportunities_tenant_pipeline",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "stage_id"],
            ["crm.pipeline_stages.tenant_id", "crm.pipeline_stages.id"],
            name="fk_crm_opportunities_tenant_stage",
        ),
        sa.CheckConstraint(
            "(amount_minor_units IS NULL) = (amount_currency IS NULL)",
            name="ck_crm_opportunities_amount_both_or_neither",
        ),
        schema="crm",
    )
    op.create_index("ix_crm_opportunities_tenant_id", "opportunities", ["tenant_id"], schema="crm")
    op.create_index(
        "ix_crm_opportunities_contact_id", "opportunities", ["contact_id"], schema="crm"
    )
    op.create_index(
        "ix_crm_opportunities_company_id", "opportunities", ["company_id"], schema="crm"
    )
    op.create_index("ix_crm_opportunities_stage_id", "opportunities", ["stage_id"], schema="crm")

    for statement in tenant_rls_statements("opportunities", schema="crm"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.opportunities TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("opportunities", schema="crm")
