"""create accounting.payments table

Revision ID: 0062_accounting_payments
Revises: 0061_accounting_bill_lines
Create Date: 2026-09-29 00:00:06.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 8 (+ addendum). No separate
lifecycle/status column -- `unallocated_amount` is the single source of
truth for how much of a payment remains unapplied. No cash-leg journal
entry is created for a payment this phase (Decision 8's own explicit
exclusion).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0062_accounting_payments"
down_revision: str | Sequence[str] | None = "0061_accounting_bill_lines"
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
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("unallocated_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_payments_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_payments_tenant_contact",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')", name="ck_accounting_payments_direction"
        ),
        sa.CheckConstraint("amount > 0", name="ck_accounting_payments_amount_positive"),
        sa.CheckConstraint(
            "unallocated_amount >= 0 AND unallocated_amount <= amount",
            name="ck_accounting_payments_unallocated_bounds",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_payments_tenant_id", "payments", ["tenant_id"], schema="accounting"
    )
    op.create_index(
        "ix_accounting_payments_contact_id", "payments", ["contact_id"], schema="accounting"
    )

    for statement in tenant_rls_statements("payments", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.payments TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("payments", schema="accounting")
