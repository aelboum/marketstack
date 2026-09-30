"""create accounting.bank_accounts table

Revision ID: 0069_bank_accounts
Revises: 0068_credit_note_lines
Create Date: 2026-09-30 00:00:00.000000

docs/ROADMAP.md Phase 15.5 ("Banking -- manual import and reconciliation").
Metadata-only (`docs/ACCOUNTING-SCOPE.md` "Banking": "not live
aggregation") -- `ledger_account_id`'s FK to `accounting.accounts` carries
no `ON DELETE` clause (default `RESTRICT`): the chart-of-accounts entry a
bank account posts against must never be deletable out from under it. One
bank account per ledger account
(`uq_accounting_bank_accounts_tenant_ledger_account`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0069_bank_accounts"
down_revision: str | Sequence[str] | None = "0068_credit_note_lines"
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
        "bank_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_bank_accounts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "ledger_account_id",
            name="uq_accounting_bank_accounts_tenant_ledger_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ledger_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bank_accounts_tenant_ledger_account",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_accounts_tenant_id", "bank_accounts", ["tenant_id"], schema="accounting"
    )

    for statement in tenant_rls_statements("bank_accounts", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.bank_accounts TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("bank_accounts", schema="accounting")
