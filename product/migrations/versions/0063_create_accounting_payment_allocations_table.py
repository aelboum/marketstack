"""create accounting.payment_allocations table

Revision ID: 0063_accounting_payment_allocs
Revises: 0062_accounting_payments
Create Date: 2026-09-29 00:00:07.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 8 (+ addendum). `document_type`
/`document_id` is a deliberately soft, application-level polymorphic
reference (never a hard FK -- a payment allocates against exactly one of
two different tables; `product/accounting/payments.py::create_allocation()`
re-reads the target row through the same tenant's session before
allocating). Immutable once created -- `reverses_allocation_id` is set
only on the new row a reversal creates; a reversal's `amount` restores the
same magnitude, never a signed/negative amount.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0063_accounting_payment_allocs"
down_revision: str | Sequence[str] | None = "0062_accounting_payments"
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
        "payment_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=7), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reverses_allocation_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_accounting_payment_allocations_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["accounting.payments.tenant_id", "accounting.payments.id"],
            name="fk_accounting_payment_allocations_tenant_payment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_allocation_id"],
            [
                "accounting.payment_allocations.tenant_id",
                "accounting.payment_allocations.id",
            ],
            name="fk_accounting_payment_allocations_tenant_reverses",
        ),
        sa.CheckConstraint(
            "document_type IN ('invoice', 'bill')",
            name="ck_accounting_payment_allocations_document_type",
        ),
        sa.CheckConstraint("amount > 0", name="ck_accounting_payment_allocations_amount_positive"),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_payment_allocations_tenant_id",
        "payment_allocations",
        ["tenant_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_payment_allocations_payment_id",
        "payment_allocations",
        ["payment_id"],
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_payment_allocations_document",
        "payment_allocations",
        ["tenant_id", "document_type", "document_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("payment_allocations", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.payment_allocations TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("payment_allocations", schema="accounting")
