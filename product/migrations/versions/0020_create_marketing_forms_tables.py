"""create marketing.forms and marketing.form_submissions tables

Revision ID: 0020_marketing_forms
Revises: 0019_crm_contacts_email_index
Create Date: 2026-09-21 00:00:06.000000

docs/ROADMAP.md Phase 6.3 (forms and lead capture).

`marketing.forms` is deliberately NOT RLS-scoped, mirroring
`white_label.tenant_domains`'s own precedent exactly (see that table's
migration, 0003, and `product/white_label/domains.py`'s own docstring for
the full reasoning): the whole point of a form's `form_token` is
resolving `tenant_id` *from* the token, before any tenant context exists
-- an RLS policy keyed on a not-yet-known `app.tenant_id` would make that
resolution impossible. `form_token` therefore carries a real, standalone
`UNIQUE` constraint (global, not composite with `tenant_id`) alongside
the ordinary `uq_marketing_forms_tenant_id_id` composite-FK target. The
ordinary tenant-scoped CRUD operations on this table (a tenant managing
its own forms) still go through `tenant_session_scope()` as normal --
only the public, token-based resolution function
(`product/marketing/forms.py::resolve_form_by_token()`) uses a plain,
untenanted `session_scope()` read.

`marketing.form_submissions`, by contrast, is an ordinary RLS-scoped
tenant-owned table (nothing about a stored submission record itself needs
resolving before a tenant context exists -- only the initial form lookup
does). `contact_id` is a composite FK into `crm.contacts`, column-scoped
`ON DELETE SET NULL (contact_id)` -- the same correct pattern every
table since the deferred Phase 4 CRM bug's discovery has used.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0020_marketing_forms"
down_revision: str | Sequence[str] | None = "0019_crm_contacts_email_index"
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
        "forms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("form_token", sa.String(length=64), nullable=False),
        sa.Column("field_definitions", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_marketing_forms_tenant_id_id"),
        # Global uniqueness -- NOT composite with tenant_id. See module
        # docstring: the token is what resolves tenant_id, so a composite
        # unique would be backwards.
        sa.UniqueConstraint("form_token", name="uq_marketing_forms_form_token"),
        schema="marketing",
    )
    op.create_index("ix_marketing_forms_tenant_id", "forms", ["tenant_id"], schema="marketing")

    # No tenant_rls_statements() call for `forms` -- see module docstring.
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.forms TO "{app_role}"')

    op.create_table(
        "form_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_data", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_marketing_form_submissions_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["marketing.forms.tenant_id", "marketing.forms.id"],
            name="fk_marketing_form_submissions_tenant_form",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_form_submissions_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_form_submissions_tenant_id",
        "form_submissions",
        ["tenant_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_form_submissions_form_id",
        "form_submissions",
        ["form_id"],
        schema="marketing",
    )

    for statement in tenant_rls_statements("form_submissions", schema="marketing"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.form_submissions TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("form_submissions", schema="marketing")
    op.drop_table("forms", schema="marketing")
