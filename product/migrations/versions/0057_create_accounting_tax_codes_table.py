"""create accounting.tax_codes table

Revision ID: 0057_accounting_tax_codes
Revises: 0056_accounting_contact_profiles
Create Date: 2026-09-29 00:00:01.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 7. A tenant-owned tax-rate
catalog -- no rate/jurisdiction is seeded here or anywhere in this
module's code; a tenant creates its own codes. `tax_account_id` is
required: a tax code's own collected/paid amounts always post to a real
GL account when an invoice/bill line using it is posted.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0057_accounting_tax_codes"
down_revision: str | Sequence[str] | None = "0056_accounting_contact_profiles"
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
        "tax_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rate_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("tax_type", sa.String(length=8), nullable=False),
        sa.Column("tax_account_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_tax_codes_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_accounting_tax_codes_tenant_code"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tax_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_tax_codes_tenant_account",
        ),
        sa.CheckConstraint(
            "tax_type IN ('sales', 'purchase')", name="ck_accounting_tax_codes_type"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_accounting_tax_codes_effective_range",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_tax_codes_tenant_id", "tax_codes", ["tenant_id"], schema="accounting"
    )

    for statement in tenant_rls_statements("tax_codes", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.tax_codes TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("tax_codes", schema="accounting")
