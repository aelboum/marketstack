"""create websites.lead_submissions table

Revision ID: 0050_websites_lead_submissions
Revises: 0049_crm_opp_assigned_user
Create Date: 2026-09-22 00:00:01.000000

docs/ROADMAP.md Phase 22 ("Lead Capture & Qualification Loop"), scope item
(a). Ordinary RLS-scoped, tenant-owned data, reached only after
`websites.websites`/`websites.pages` lookup has already established
`tenant_id` -- see `product/websites/models.py::LeadSubmission`'s own
module docstring.

`contact_id` composite-FKs against `crm.contacts`' own
`UniqueConstraint(tenant_id, id)` (0005) -- the one, ADR-0015-sanctioned
`websites -> crm` database reference, column-scoped `ON DELETE SET NULL
(contact_id)` (never a bare `SET NULL`, which would null the `NOT NULL`
`tenant_id` too) -- mirrors `product/appointments/models.py
::Appointment.contact_id`'s identical, already-shipped shape exactly.

**Also adds `uq_websites_pages_tenant_id_id`** -- `websites.pages` (0043)
was never itself a composite-FK target before this phase (nothing
referenced it), so it carries no `UniqueConstraint(tenant_id, id)` yet;
`lead_submissions.page_id` needs one to composite-FK against, per this
product's own "every cross-table reference targets a `(tenant_id, id)`
unique index, never a bare id" discipline
(`product/websites/models.py::Page`'s own updated module docstring).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0050_websites_lead_submissions"
down_revision: str | Sequence[str] | None = "0049_crm_opp_assigned_user"
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

    op.create_unique_constraint(
        "uq_websites_pages_tenant_id_id", "pages", ["tenant_id", "id"], schema="websites"
    )

    op.create_table(
        "lead_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "website_id"],
            ["websites.websites.tenant_id", "websites.websites.id"],
            name="fk_websites_lead_submissions_tenant_website",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["websites.pages.tenant_id", "websites.pages.id"],
            name="fk_websites_lead_submissions_tenant_page",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_websites_lead_submissions_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        schema="websites",
    )
    op.create_index(
        "ix_websites_lead_submissions_tenant_id",
        "lead_submissions",
        ["tenant_id"],
        schema="websites",
    )
    op.create_index(
        "ix_websites_lead_submissions_website_id",
        "lead_submissions",
        ["website_id"],
        schema="websites",
    )
    op.create_index(
        "ix_websites_lead_submissions_page_id",
        "lead_submissions",
        ["page_id"],
        schema="websites",
    )
    op.create_index(
        "ix_websites_lead_submissions_contact_id",
        "lead_submissions",
        ["contact_id"],
        schema="websites",
    )

    for statement in tenant_rls_statements("lead_submissions", schema="websites"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON websites.lead_submissions TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("lead_submissions", schema="websites")
    op.drop_constraint("uq_websites_pages_tenant_id_id", "pages", schema="websites", type_="unique")
