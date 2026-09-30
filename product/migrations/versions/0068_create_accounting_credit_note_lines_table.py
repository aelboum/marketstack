"""create accounting.credit_note_lines table

Revision ID: 0068_credit_note_lines
Revises: 0067_accounting_credit_notes
Create Date: 2026-09-30 00:00:01.000000

docs/ROADMAP.md Phase 15.3. Fully immutable once the parent credit note
posts, mirroring `invoice_lines`' own complete-immutability shape
(migration 0059). `credit_note_id` is `ON DELETE CASCADE` (a line has no
meaning without its credit note); `account_id`/`tax_code_id` carry no
`ON DELETE` clause (default `RESTRICT`).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0068_credit_note_lines"
down_revision: str | Sequence[str] | None = "0067_accounting_credit_notes"
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
        "credit_note_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("credit_note_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("tax_code_id", sa.Uuid(), nullable=True),
        sa.Column("line_subtotal", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("line_tax", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_credit_note_lines_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "credit_note_id"],
            ["accounting.credit_notes.tenant_id", "accounting.credit_notes.id"],
            name="fk_accounting_credit_note_lines_tenant_credit_note",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_credit_note_lines_tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tax_code_id"],
            ["accounting.tax_codes.tenant_id", "accounting.tax_codes.id"],
            name="fk_accounting_credit_note_lines_tenant_tax_code",
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_accounting_credit_note_lines_quantity_positive"
        ),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_accounting_credit_note_lines_unit_price_non_negative"
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_credit_note_lines_tenant_id",
        "credit_note_lines",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_credit_note_lines_credit_note_id",
        "credit_note_lines",
        ["credit_note_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("credit_note_lines", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.credit_note_lines TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("credit_note_lines", schema="accounting")
