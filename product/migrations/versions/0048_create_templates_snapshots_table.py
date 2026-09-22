"""create templates.snapshots table

Revision ID: 0048_templates_snapshots
Revises: 0047_billing_resale_plans
Create Date: 2026-09-22 00:00:00.000000

docs/ROADMAP.md Phase 14.1. First (and, in this phase, only) table in the
`templates` schema -- creates the schema itself, mirroring
`reputation.review_requests`'s own 0044 precedent: the migration that
creates the schema is also the one whose downgrade drops it.

Ordinary RLS-scoped, tenant-owned data. No composite FK to any other
product table -- see `product/templates/models.py::Snapshot`'s own module
docstring: this is the only product-owned table Phase 14 introduces, and
its `payload` column never contains a foreign identifier of any kind
(`docs/ADR/0013-templates-snapshot-scope-and-crm-dependency.md`'s own
"Decision 2").

`ck_templates_snapshots_payload_size` bounds `payload` to 256 KiB --
mirrors `product/websites/models.py::Page.content_blocks`'s own "bounded
JSON, never an unbounded blob" discipline.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0048_templates_snapshots"
down_revision: str | Sequence[str] | None = "0047_billing_resale_plans"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS templates")
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "included_domains", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_templates_snapshots_schema_version"),
        sa.CheckConstraint(
            "octet_length(payload::text) <= 262144", name="ck_templates_snapshots_payload_size"
        ),
        schema="templates",
    )
    op.create_index(
        "ix_templates_snapshots_tenant_id", "snapshots", ["tenant_id"], schema="templates"
    )

    for statement in tenant_rls_statements("snapshots", schema="templates"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA templates TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON templates.snapshots TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA templates "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA templates "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("snapshots", schema="templates")
    op.execute("DROP SCHEMA IF EXISTS templates")
