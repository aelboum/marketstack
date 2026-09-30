"""create accounting.credit_notes table

Revision ID: 0067_accounting_credit_notes
Revises: 0066_transfer_attempt_id
Create Date: 2026-09-30 00:00:00.000000

docs/ROADMAP.md Phase 15.3 ("Credit notes" -- deferred by Phase 25's own
explicit scope note, implemented separately once Phase 25's invoice
foundation existed to reference). `credit_note_number` is `NULL` while
`draft`, assigned only by `post_credit_note()` under its own tenant-wide
gapless-numbering advisory lock -- a separate sequence from
`invoices.invoice_number` (mirrors that table's own "resolved only at
posting" shape, migration 0058's own docstring). The partial unique index
below (`WHERE credit_note_number IS NOT NULL`) is the same
database-enforced backstop behind the advisory lock's own serialization.
`invoice_id`'s FK to `accounting.invoices` carries no `ON DELETE` clause
(default `RESTRICT`) -- a credit note must never outlive the invoice it
corrects.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0067_accounting_credit_notes"
down_revision: str | Sequence[str] | None = "0066_transfer_attempt_id"
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
        "credit_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("credit_note_number", sa.Integer(), nullable=True),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=6), nullable=False, server_default="draft"),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_credit_notes_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["accounting.invoices.tenant_id", "accounting.invoices.id"],
            name="fk_accounting_credit_notes_tenant_invoice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_credit_notes_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_credit_notes_tenant_journal_entry",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'voided')",
            name="ck_accounting_credit_notes_status",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_credit_notes_tenant_id", "credit_notes", ["tenant_id"], schema="accounting"
    )
    op.create_index(
        "ix_accounting_credit_notes_invoice_id",
        "credit_notes",
        ["invoice_id"],
        schema="accounting",
    )
    # Gapless-numbering backstop (module docstring): unique only among
    # posted (non-NULL) numbers -- many drafts may coexist with
    # credit_note_number IS NULL without ever colliding.
    op.create_index(
        "uq_accounting_credit_notes_tenant_number",
        "credit_notes",
        ["tenant_id", "credit_note_number"],
        unique=True,
        schema="accounting",
        postgresql_where=sa.text("credit_note_number IS NOT NULL"),
    )

    for statement in tenant_rls_statements("credit_notes", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.credit_notes TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("credit_notes", schema="accounting")
