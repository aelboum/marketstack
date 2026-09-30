"""create accounting.bank_statement_lines table

Revision ID: 0071_bank_statement_lines
Revises: 0070_bank_statements
Create Date: 2026-09-30 00:00:02.000000

docs/ROADMAP.md Phase 15.5. `line_hash` backs
`uq_accounting_bank_statement_lines_tenant_account_hash` -- the
duplicate-import backstop (`product/accounting/models.py
::BankStatementLine`'s own module docstring): re-importing an overlapping
statement recomputes the identical hash for overlapping lines, so
`product/accounting/banking.py::import_bank_statement_csv()` can skip them
via `IntegrityError` translation rather than double-counting.
`bank_statement_id` is `ON DELETE CASCADE` (a line has no meaning without
its statement); `bank_account_id`/`matched_payment_id`/
`matched_account_id`/`journal_entry_id` carry no `ON DELETE` clause
(default `RESTRICT`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0071_bank_statement_lines"
down_revision: str | Sequence[str] | None = "0070_bank_statements"
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
        "bank_statement_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("bank_statement_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("counterparty_reference", sa.String(length=255), nullable=True),
        sa.Column("line_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="unmatched"),
        sa.Column("matched_document_type", sa.String(length=7), nullable=True),
        sa.Column("matched_document_id", sa.Uuid(), nullable=True),
        sa.Column("matched_payment_id", sa.Uuid(), nullable=True),
        sa.Column("matched_account_id", sa.Uuid(), nullable=True),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column(
            "reconciled_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=True
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_accounting_bank_statement_lines_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "line_hash",
            name="uq_accounting_bank_statement_lines_tenant_account_hash",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bank_statement_id"],
            ["accounting.bank_statements.tenant_id", "accounting.bank_statements.id"],
            name="fk_accounting_bank_statement_lines_tenant_statement",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bank_account_id"],
            ["accounting.bank_accounts.tenant_id", "accounting.bank_accounts.id"],
            name="fk_accounting_bank_statement_lines_tenant_bank_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "matched_payment_id"],
            ["accounting.payments.tenant_id", "accounting.payments.id"],
            name="fk_accounting_bank_statement_lines_tenant_payment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "matched_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bank_statement_lines_tenant_matched_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_bank_statement_lines_tenant_journal_entry",
        ),
        sa.CheckConstraint("amount != 0", name="ck_accounting_bank_statement_lines_amount_nonzero"),
        sa.CheckConstraint(
            "status IN ('unmatched', 'reconciled')",
            name="ck_accounting_bank_statement_lines_status",
        ),
        sa.CheckConstraint(
            "matched_document_type IS NULL OR matched_document_type IN ('invoice', 'bill')",
            name="ck_accounting_bank_statement_lines_matched_document_type",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_statement_lines_tenant_id",
        "bank_statement_lines",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_statement_lines_bank_statement_id",
        "bank_statement_lines",
        ["bank_statement_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_statement_lines_status",
        "bank_statement_lines",
        ["tenant_id", "status"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("bank_statement_lines", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.bank_statement_lines TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("bank_statement_lines", schema="accounting")
