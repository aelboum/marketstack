"""create marketing.templates table

Revision ID: 0021_marketing_templates
Revises: 0020_marketing_forms
Create Date: 2026-09-21 00:00:07.000000

docs/ROADMAP.md Phase 6.4 (landing page and campaign templates).
`template_type = "landing_page"` here is a stored content blob only --
NOT a page builder or rendering engine (Phase 11 owns that; see
`product/marketing/templates.py`'s own module docstring). Ordinary
tenant-owned, RLS-scoped table -- no composite FK, this table has no
cross-table reference of its own (`marketing.campaigns.template_id`, the
reference in the other direction, is added by the next migration).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0021_marketing_templates"
down_revision: str | Sequence[str] | None = "0020_marketing_forms"
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
        "templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("template_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_marketing_templates_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_marketing_templates_tenant_name"),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_templates_tenant_id", "templates", ["tenant_id"], schema="marketing"
    )

    for statement in tenant_rls_statements("templates", schema="marketing"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.templates TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("templates", schema="marketing")
