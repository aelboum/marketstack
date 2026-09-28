"""create accounting.invoices table

Revision ID: 0058_accounting_invoices
Revises: 0057_accounting_tax_codes
Create Date: 2026-09-29 00:00:02.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 12. `invoice_number` is
`NULL` while `draft`, assigned only by `post_invoice()` under the
tenant-wide gapless-numbering advisory lock -- the partial unique index
below (`WHERE invoice_number IS NOT NULL`) is what makes a number
collision structurally impossible once two concurrent posts *do* land,
the database-enforced backstop behind the advisory lock's own
serialization (defense in depth, matching this module's own established
discipline everywhere else). `contact_id`'s FK to `crm.contacts` carries
no `ON DELETE` clause (default `RESTRICT`) -- defense in depth alongside
`accounting.contact_profiles`' own identical RESTRICT, per ADR-0014
Decision 6's addendum: a posted invoice must never lose its counterparty.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0058_accounting_invoices"
down_revision: str | Sequence[str] | None = "0057_accounting_tax_codes"
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
        "invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("invoice_number", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("receivable_account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False, server_default="draft"),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_invoices_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_invoices_tenant_contact",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receivable_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_invoices_tenant_receivable_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_invoices_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_invoices_tenant_journal_entry",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'cancelled', 'voided')",
            name="ck_accounting_invoices_status",
        ),
        sa.CheckConstraint("due_date >= issue_date", name="ck_accounting_invoices_due_after_issue"),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_invoices_tenant_id", "invoices", ["tenant_id"], schema="accounting"
    )
    op.create_index(
        "ix_accounting_invoices_contact_id", "invoices", ["contact_id"], schema="accounting"
    )
    # Gapless-numbering backstop (module docstring): unique only among
    # posted (non-NULL) numbers -- many drafts may coexist with
    # invoice_number IS NULL without ever colliding.
    op.create_index(
        "uq_accounting_invoices_tenant_number",
        "invoices",
        ["tenant_id", "invoice_number"],
        unique=True,
        schema="accounting",
        postgresql_where=sa.text("invoice_number IS NOT NULL"),
    )

    for statement in tenant_rls_statements("invoices", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.invoices TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("invoices", schema="accounting")
