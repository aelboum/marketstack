"""create marketing.campaigns table

Revision ID: 0016_marketing_campaigns
Revises: 0015_conversations_templates
Create Date: 2026-09-21 00:00:02.000000

docs/ROADMAP.md Phase 6.1. First table in the `marketing` schema --
creates the schema itself (mirrors crm.companies' own 0004 migration and
conversations.threads' own 0013 migration: the migration that creates
the schema is also the one whose downgrade drops it). No composite FK on
this table -- `campaigns` is the root of this schema; `segment_query` is
a plain text column (JSON serialized at the application layer,
product/marketing/segmentation.py), never a database-level query
construct.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0016_marketing_campaigns"
down_revision: str | Sequence[str] | None = "0015_conversations_templates"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS marketing")
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("segment_query", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_marketing_campaigns_tenant_id_id"),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_campaigns_tenant_id", "campaigns", ["tenant_id"], schema="marketing"
    )

    for statement in tenant_rls_statements("campaigns", schema="marketing"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA marketing TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.campaigns TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA marketing "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA marketing "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("campaigns", schema="marketing")
    op.execute("DROP SCHEMA IF EXISTS marketing")
