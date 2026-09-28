"""create accounting.accounts table

Revision ID: 0052_accounting_accounts
Revises: 0051_appointments_cal_events
Create Date: 2026-09-27 00:00:00.000000

docs/ROADMAP.md Phase 24 ("Mini Accounting Foundation"). First table in
the `accounting` schema -- creates the schema itself, mirroring
`reputation.review_requests`'s own 0044 precedent: the migration that
creates the schema is also the one whose downgrade drops it (after
0053-0055's own tables, which depend on this one, have already been
dropped by their own downgrades).

Ordinary RLS-scoped, tenant-owned data. `code` is unique per tenant
(`uq_accounting_accounts_tenant_code`) -- a tenant's own chart-of-accounts
numbering is its own to define (`docs/ACCOUNTING-SCOPE.md`), never
globally unique across tenants. `account_type` carries a real
`CheckConstraint`, not only service-layer validation -- mirrors
`product/appointments/models.py::AvailabilityRule`'s own bounds-checking
precedent.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0052_accounting_accounts"
down_revision: str | Sequence[str] | None = "0051_appointments_cal_events"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS accounting")
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_accounts_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_accounting_accounts_tenant_code"),
        sa.CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')",
            name="ck_accounting_accounts_account_type",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_accounts_tenant_id", "accounts", ["tenant_id"], schema="accounting"
    )

    for statement in tenant_rls_statements("accounts", schema="accounting"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA accounting TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.accounts TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA accounting "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA accounting "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("accounts", schema="accounting")
    op.execute("DROP SCHEMA IF EXISTS accounting")
