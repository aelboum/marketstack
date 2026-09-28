"""create accounting.bills table

Revision ID: 0060_accounting_bills
Revises: 0059_accounting_invoice_lines
Create Date: 2026-09-29 00:00:04.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 12 -- the purchase-side
mirror of `accounting.invoices`, with one deliberate asymmetry: no
internally generated gapless number. Gapless sequential numbering is a
legal requirement for invoices a tenant *issues*, never for bills a
tenant *receives* -- duplicate detection instead uses the supplier's own
`supplier_reference` (`uq_accounting_bills_tenant_contact_reference`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0060_accounting_bills"
down_revision: str | Sequence[str] | None = "0059_accounting_invoice_lines"
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
        "bills",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("supplier_reference", sa.String(length=100), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("payable_account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False, server_default="draft"),
        sa.Column("bill_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("outstanding_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("period_id", sa.Uuid(), nullable=True),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("posted_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_bills_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "contact_id",
            "supplier_reference",
            name="uq_accounting_bills_tenant_contact_reference",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_bills_tenant_contact",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bills_tenant_payable_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_bills_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_bills_tenant_journal_entry",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'cancelled', 'voided')",
            name="ck_accounting_bills_status",
        ),
        sa.CheckConstraint("due_date >= bill_date", name="ck_accounting_bills_due_after_bill_date"),
        schema="accounting",
    )
    op.create_index("ix_accounting_bills_tenant_id", "bills", ["tenant_id"], schema="accounting")
    op.create_index("ix_accounting_bills_contact_id", "bills", ["contact_id"], schema="accounting")

    for statement in tenant_rls_statements("bills", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.bills TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("bills", schema="accounting")
