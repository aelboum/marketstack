"""create accounting.journal_lines table

Revision ID: 0055_accounting_journal_lines
Revises: 0054_accounting_journal_entries
Create Date: 2026-09-27 00:00:03.000000

docs/ROADMAP.md Phase 24, ADR-0014 Decision 4. `debit_amount`/
`credit_amount` are `NUMERIC(18, 2)` -- never floating point, never
integer minor units (Decision 4's own reasoning, `product/accounting
/models.py`'s module docstring). `ck_accounting_journal_lines_exactly_one
_side` is the schema-level half of the double-entry invariant: exactly
one of the two columns is strictly positive, the other exactly zero --
never both zero, never both positive, never negative. Entry-level balance
(`sum(debits) == sum(credits)` across a whole entry) is **not** expressible
as a single-row `CHECK` (Postgres has no cross-row `CHECK`) and is instead
enforced by `product/accounting/journal.py::post_journal_entry()` inside
the posting transaction.

`journal_entry_id` is `ON DELETE CASCADE` (a line has no meaning without
its entry, mirrors `availability_rules.calendar_id`'s own precedent) --
declared even though no service function in this phase ever deletes a
`JournalEntry` row. `account_id` carries no `ON DELETE` behavior decision
(default `RESTRICT`) -- deliberately, per Decision 9's own explicit
requirement to prevent deleting an account referenced by a journal line.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0055_accounting_journal_lines"
down_revision: str | Sequence[str] | None = "0054_accounting_journal_entries"
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
        "journal_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("debit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_journal_lines_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_journal_lines_tenant_journal_entry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_journal_lines_tenant_account",
        ),
        sa.CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0)",
            name="ck_accounting_journal_lines_exactly_one_side",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_journal_lines_tenant_id",
        "journal_lines",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_journal_lines_journal_entry_id",
        "journal_lines",
        ["journal_entry_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_journal_lines_account_id",
        "journal_lines",
        ["account_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("journal_lines", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.journal_lines TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("journal_lines", schema="accounting")
