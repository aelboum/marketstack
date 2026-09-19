"""create crm.contacts table

Revision ID: 0005_crm_contacts
Revises: 0004_crm_companies
Create Date: 2026-09-20 00:00:01.000000

docs/ROADMAP.md Phase 4.1. `company_id` is a composite FK
`(tenant_id, company_id) -> crm.companies(tenant_id, id)`, ON DELETE
SET NULL (product/crm/models.py's own module docstring: deleting a
company unlinks, never deletes, its contacts) -- this is what makes it
structurally impossible for a contact to reference a company in a
different tenant, not merely an application-level check.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0005_crm_contacts"
down_revision: str | Sequence[str] | None = "0004_crm_companies"
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
        "contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_contacts_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_contacts_tenant_company",
            ondelete="SET NULL",
        ),
        schema="crm",
    )
    op.create_index("ix_crm_contacts_tenant_id", "contacts", ["tenant_id"], schema="crm")
    op.create_index("ix_crm_contacts_company_id", "contacts", ["company_id"], schema="crm")

    for statement in tenant_rls_statements("contacts", schema="crm"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.contacts TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("contacts", schema="crm")
