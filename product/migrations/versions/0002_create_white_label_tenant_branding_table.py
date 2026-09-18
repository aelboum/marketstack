"""create white_label.tenant_branding table

Revision ID: 0002_white_label_tenant_branding
Revises: 0001_foundation_tenant_settings
Create Date: 2026-09-19 00:00:01.000000

docs/ROADMAP.md Phase 2.3; docs/WHITE-LABEL.md section 2. RLS via
`infra.db.rls.tenant_rls_statements()` -- each tenant only ever reads/
writes its own branding row directly; the fallback-chain *resolution*
across ancestors (product/white_label/branding.py) opens one
`tenant_session_scope(ancestor_id)` per ancestor rather than bypassing
RLS, so this table's RLS policy is unchanged from every other tenant-
owned table's.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0002_white_label_tenant_branding"
down_revision: str | Sequence[str] | None = "0001_foundation_tenant_settings"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS white_label")
    op.create_table(
        "tenant_branding",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("logo_asset_ref", sa.String(length=1024), nullable=True),
        sa.Column("favicon_asset_ref", sa.String(length=1024), nullable=True),
        sa.Column("color_primary", sa.String(length=32), nullable=True),
        sa.Column("color_secondary", sa.String(length=32), nullable=True),
        sa.Column("color_accent", sa.String(length=32), nullable=True),
        sa.Column("typography", sa.String(length=255), nullable=True),
        sa.Column("login_branding_overrides", sa.Text(), nullable=True),
        sa.Column("email_from_name", sa.String(length=255), nullable=True),
        sa.Column("email_reply_to", sa.String(length=255), nullable=True),
        sa.Column("support_contact", sa.String(length=255), nullable=True),
        sa.Column("legal_terms_url", sa.String(length=1024), nullable=True),
        sa.Column("legal_privacy_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="white_label",
    )

    for statement in tenant_rls_statements("tenant_branding", schema="white_label"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA white_label TO "{app_role}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON white_label.tenant_branding TO "{app_role}"'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA white_label "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA white_label "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("tenant_branding", schema="white_label")
    op.execute("DROP SCHEMA IF EXISTS white_label")
