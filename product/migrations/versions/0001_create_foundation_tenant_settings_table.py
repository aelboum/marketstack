"""create foundation.tenant_settings table

Revision ID: 0001_foundation_tenant_settings
Revises:
Create Date: 2026-09-19 00:00:00.000000

This product's own first migration (docs/ROADMAP.md Phase 2.1).
Mirrors saas-os/examples/reference-consumer's own migration exactly:
own schema, `tenant_id` as a real foreign key into `core.tenants` (so
SaaS-OS's own migrations must already have run -- ADR-0016's fixed
ordering, enforced by scripts/bootstrap-db.py), RLS via
`infra.db.rls.tenant_rls_statements()` rather than hand-rolled DDL, and
explicit GRANTs to the restricted runtime role (never the migration
role itself).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0001_foundation_tenant_settings"
down_revision: str | Sequence[str] | None = None
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

    op.execute("CREATE SCHEMA IF NOT EXISTS foundation")
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), primary_key=True),
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="foundation",
    )
    op.create_index(
        "ix_foundation_tenant_settings_tenant_id",
        "tenant_settings",
        ["tenant_id"],
        schema="foundation",
    )

    for statement in tenant_rls_statements("tenant_settings", schema="foundation"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA foundation TO "{app_role}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON foundation.tenant_settings TO "{app_role}"'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA foundation "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA foundation "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("tenant_settings", schema="foundation")
    op.execute("DROP SCHEMA IF EXISTS foundation")
