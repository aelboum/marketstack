"""create billing.resale_plans table

Revision ID: 0047_billing_resale_plans
Revises: 0046_reputation_review_responses
Create Date: 2026-09-21 00:00:05.000000

docs/ROADMAP.md Phase 13.2. First (and, in this phase, only) table in the
`billing` schema -- creates the schema itself, mirroring
`reputation.review_requests`'s own 0044 precedent: the migration that
creates the schema is also the one whose downgrade drops it.

Ordinary RLS-scoped, tenant-owned data (`tenant_id` is the RESELLER
tenant, `docs/ADR/0012-resale-billing-ownership-model.md`). No composite
FK to any other product table -- see
`product/billing/models.py::ResalePlan`'s own module docstring: this is
the only product-owned table Phase 13 introduces; subscriptions
themselves live entirely in SaaS-OS's own `core.billing_subscriptions`.

`(tenant_id, key)` is unique per reseller; `underlying_plan_key` is
globally unique (it maps 1:1 onto a `core.billing_plans.key`, which
itself carries a global `UNIQUE` constraint).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0047_billing_resale_plans"
down_revision: str | Sequence[str] | None = "0046_reputation_review_responses"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS billing")
    op.create_table(
        "resale_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("price_amount", sa.Integer(), nullable=False),
        sa.Column("price_currency", sa.String(length=3), nullable=False),
        sa.Column("billing_interval", sa.String(length=16), nullable=False, server_default="month"),
        sa.Column("entitlements", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="enabled"),
        sa.Column("underlying_plan_key", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "key", name="uq_billing_resale_plans_tenant_key"),
        sa.UniqueConstraint(
            "underlying_plan_key", name="uq_billing_resale_plans_underlying_plan_key"
        ),
        sa.CheckConstraint(
            "status IN ('enabled', 'disabled')", name="ck_billing_resale_plans_status"
        ),
        sa.CheckConstraint(
            "billing_interval IN ('month', 'year')",
            name="ck_billing_resale_plans_billing_interval",
        ),
        sa.CheckConstraint("price_amount >= 0", name="ck_billing_resale_plans_price_amount"),
        schema="billing",
    )
    op.create_index(
        "ix_billing_resale_plans_tenant_id", "resale_plans", ["tenant_id"], schema="billing"
    )

    for statement in tenant_rls_statements("resale_plans", schema="billing"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA billing TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON billing.resale_plans TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA billing "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA billing "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("resale_plans", schema="billing")
    op.execute("DROP SCHEMA IF EXISTS billing")
