"""create white_label.tenant_domains table

Revision ID: 0003_white_label_tenant_domains
Revises: 0002_white_label_tenant_branding
Create Date: 2026-09-19 00:00:02.000000

docs/ROADMAP.md Phase 2.4; docs/WHITE-LABEL.md section 3. Deliberately
NO Row-Level Security on this table -- it must be readable before a
tenant context exists (domain resolution is what discovers the tenant),
mirroring `core.tenancy.TenantAncestry`'s own documented "not RLS-
scoped... untenanted" precedent (see product/white_label/models.py's
`TenantDomain` docstring). Schema `white_label` already exists (created
by 0002); this migration only adds its own table and grants to it, and
its own downgrade only drops its own table -- schema teardown is 0002's
downgrade's job (it runs last in the downgrade order, after this one),
since 0002's own table would otherwise still be present in the schema
when this migration's downgrade runs.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_white_label_tenant_domains"
down_revision: str | Sequence[str] | None = "0002_white_label_tenant_branding"
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
        "tenant_domains",
        sa.Column("domain", sa.String(length=255), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("tls_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="white_label",
    )
    op.create_index(
        "ix_white_label_tenant_domains_tenant_id",
        "tenant_domains",
        ["tenant_id"],
        schema="white_label",
    )

    # No tenant_rls_statements() call -- see module docstring. This table
    # is granted to the app role like any other, but reachable by a plain,
    # untenanted infra.db.session_scope() read, never
    # tenant_session_scope() (there is no tenant_id to scope the session
    # to until this very lookup resolves one).
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON white_label.tenant_domains TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("tenant_domains", schema="white_label")
