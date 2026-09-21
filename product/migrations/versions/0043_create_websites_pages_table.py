"""create websites.pages table

Revision ID: 0043_websites_pages
Revises: 0042_websites_websites
Create Date: 2026-09-21 00:00:01.000000

docs/ROADMAP.md Phase 11.1. Ordinary RLS-scoped, tenant-owned data,
reached only after `websites.websites` lookup has already established
`tenant_id` -- see `product/websites/models.py::Page`'s own module
docstring. `slug` is unique only within its own website
(`UniqueConstraint(tenant_id, website_id, slug)`), unlike
`websites.slug` itself (globally unique, 0042) -- once the website is
resolved, no further untenanted lookup is needed.

`website_id` composite-FKs against `websites.websites`' own
`UniqueConstraint(tenant_id, id)` (0042), never a bare `ForeignKey` on
the id column alone -- structurally impossible for a page row to
reference another tenant's website. `ON DELETE CASCADE`: a page has no
meaning without its own website.

`content_blocks`/`published_content_blocks` are bounded JSON -- a closed,
typed block vocabulary validated by `product/websites/content_blocks.py`
before ever reaching this table (`product/websites/models.py::Page`'s
own module docstring on the draft/published split), never an unrestricted
blob.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0043_websites_pages"
down_revision: str | Sequence[str] | None = "0042_websites_websites"
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
        "pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column(
            "content_blocks", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("published_content_blocks", sa.JSON(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "website_id"],
            ["websites.websites.tenant_id", "websites.websites.id"],
            name="fk_websites_pages_tenant_website",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "website_id", "slug", name="uq_websites_pages_tenant_website_slug"
        ),
        schema="websites",
    )
    op.create_index("ix_websites_pages_tenant_id", "pages", ["tenant_id"], schema="websites")
    op.create_index("ix_websites_pages_website_id", "pages", ["website_id"], schema="websites")

    for statement in tenant_rls_statements("pages", schema="websites"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON websites.pages TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("pages", schema="websites")
