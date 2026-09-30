"""create accounting.bank_statements table

Revision ID: 0070_bank_statements
Revises: 0069_bank_accounts
Create Date: 2026-09-30 00:00:01.000000

docs/ROADMAP.md Phase 15.5. One imported bank statement, covering one
period, against one `BankAccount`. `bank_account_id`'s FK carries no `ON
DELETE` clause (default `RESTRICT`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0070_bank_statements"
down_revision: str | Sequence[str] | None = "0069_bank_accounts"
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
        "bank_statements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("period_start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_bank_statements_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bank_account_id"],
            ["accounting.bank_accounts.tenant_id", "accounting.bank_accounts.id"],
            name="fk_accounting_bank_statements_tenant_bank_account",
        ),
        sa.CheckConstraint(
            "period_end_date >= period_start_date",
            name="ck_accounting_bank_statements_period_valid",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_statements_tenant_id",
        "bank_statements",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_bank_statements_bank_account_id",
        "bank_statements",
        ["bank_account_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("bank_statements", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.bank_statements TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("bank_statements", schema="accounting")
