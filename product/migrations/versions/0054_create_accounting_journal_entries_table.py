"""create accounting.journal_entries table

Revision ID: 0054_accounting_journal_entries
Revises: 0053_accounting_periods
Create Date: 2026-09-27 00:00:02.000000

docs/ROADMAP.md Phase 24, ADR-0014 Decisions 2-3. `period_id` is nullable
-- `NULL` for a `draft` entry, populated only when `post_journal_entry()`
resolves the covering period (`product/accounting/journal.py`'s own
module docstring); its FK carries no `ON DELETE` behavior decision
(default `RESTRICT`) since this phase ships no period-delete function.
`reverses_entry_id` is a nullable, self-referential composite FK, set
only on the *new* entry a reversal creates. `status` carries a real
`CheckConstraint`, mirroring every other status column in this codebase.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0054_accounting_journal_entries"
down_revision: str | Sequence[str] | None = "0053_accounting_periods"
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
        "journal_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("entry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="draft"),
        sa.Column("period_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("posted_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_journal_entries_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_journal_entries_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_journal_entries_tenant_reverses_entry",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'voided', 'reversed')",
            name="ck_accounting_journal_entries_status",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_journal_entries_tenant_id",
        "journal_entries",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_journal_entries_period_id",
        "journal_entries",
        ["period_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("journal_entries", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.journal_entries TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("journal_entries", schema="accounting")
