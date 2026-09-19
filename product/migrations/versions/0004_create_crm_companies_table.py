"""create crm.companies table

Revision ID: 0004_crm_companies
Revises: 0003_white_label_tenant_domains
Create Date: 2026-09-20 00:00:00.000000

docs/ROADMAP.md Phase 4.1. First table in the `crm` schema -- creates the
schema itself (subsequent crm migrations only add their own table, per
the same pattern white_label's 0002/0003 pair already established: the
migration that creates the schema is also the one whose downgrade drops
it, since it necessarily runs last in a full downgrade chain). RLS via
`infra.db.rls.tenant_rls_statements()`, identical to every other
tenant-owned table in this product.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0004_crm_companies"
down_revision: str | Sequence[str] | None = "0003_white_label_tenant_domains"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS crm")
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_companies_tenant_id_id"),
        schema="crm",
    )
    op.create_index("ix_crm_companies_tenant_id", "companies", ["tenant_id"], schema="crm")

    for statement in tenant_rls_statements("companies", schema="crm"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA crm TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.companies TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA crm "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA crm "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("companies", schema="crm")
    op.execute("DROP SCHEMA IF EXISTS crm")
