"""create websites.websites table

Revision ID: 0042_websites_websites
Revises: 0041_ai_tenant_policies
Create Date: 2026-09-21 00:00:00.000000

docs/ROADMAP.md Phase 11.1. First table in the `websites` schema --
creates the schema itself, mirroring `telephony.phone_numbers`'s own
0030 precedent: the migration that creates the schema is also the one
whose downgrade drops it.

**Deliberately NOT RLS-scoped**, mirroring `telephony.phone_numbers`'s
own 0030 precedent exactly: an anonymous visitor's request for a
published page carries only the website's own public `slug`, and that
must resolve to a tenant *before* any tenant context exists -- an RLS
policy keyed on a not-yet-known `app.tenant_id` would make that
resolution structurally impossible. `slug` carries a real, standalone
`UNIQUE` constraint (global, not composite with `tenant_id`).
`custom_domain` likewise carries its own standalone `UNIQUE` constraint
(nullable -- most websites have none) -- data-model only, no DNS/TLS
wiring (see `product/websites/models.py::Website`'s own module
docstring). `UniqueConstraint(tenant_id, id)` (and its mirror,
`UniqueConstraint(id, tenant_id)`, needed because `websites.pages`'
composite FK below references columns in `(tenant_id, id)` order) is
still present even without RLS -- needed for `pages`' own composite FK.

See `product/websites/models.py`'s own module docstring for the full
reasoning behind every choice in this table.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_websites_websites"
down_revision: str | Sequence[str] | None = "0041_ai_tenant_policies"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS websites")
    op.create_table(
        "websites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("custom_domain", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_websites_websites_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_websites_websites_tenant_id_id"),
        sa.UniqueConstraint("slug", name="uq_websites_websites_slug"),
        sa.UniqueConstraint("custom_domain", name="uq_websites_websites_custom_domain"),
        schema="websites",
    )
    op.create_index("ix_websites_websites_tenant_id", "websites", ["tenant_id"], schema="websites")

    # No tenant_rls_statements() call -- see module docstring.
    op.execute(f'GRANT USAGE ON SCHEMA websites TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON websites.websites TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA websites "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA websites "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("websites", schema="websites")
    op.execute("DROP SCHEMA IF EXISTS websites")
