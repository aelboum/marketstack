"""create accounting.contact_profiles table

Revision ID: 0056_accounting_contact_profiles
Revises: 0055_accounting_journal_lines
Create Date: 2026-09-29 00:00:00.000000

docs/ROADMAP.md Phase 25, ADR-0014 Decision 6 (+ its Phase 25 addendum).
The *only* thing this table adds to CRM's own contact identity -- a
`(tenant_id, contact_id)`-scoped role tag (`customer`/`supplier`/`both`).
`crm.contacts` remains the tenant's sole identity table; this migration
creates no second one, and never references `crm.companies`.

`contact_id`'s FK carries no `ON DELETE` clause (default `RESTRICT`) --
deliberately, per the ADR's own addendum: once a contact is tagged,
`product.crm.contacts.delete_contact()` fails with a raw `IntegrityError`,
a disclosed, accepted trade-off (see that addendum for the full
reasoning). `product/crm/` is not modified by this migration.

This is `product.accounting`'s first real edge into `crm.contacts` --
`pyproject.toml`'s own import-linter contracts are updated in the same
commit as this migration to permit `product.accounting -> product.crm`
(never the reverse), mirroring `product/templates/__init__.py`'s own pair
exactly.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0056_accounting_contact_profiles"
down_revision: str | Sequence[str] | None = "0055_accounting_journal_lines"
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
        "contact_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounting_contact_profiles_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "contact_id", name="uq_accounting_contact_profiles_tenant_contact"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_contact_profiles_tenant_contact",
        ),
        sa.CheckConstraint(
            "role IN ('customer', 'supplier', 'both')",
            name="ck_accounting_contact_profiles_role",
        ),
        schema="accounting",
    )
    op.create_index(
        "ix_accounting_contact_profiles_tenant_id",
        "contact_profiles",
        ["tenant_id"],
        schema="accounting",
    )

    for statement in tenant_rls_statements("contact_profiles", schema="accounting"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.contact_profiles TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("contact_profiles", schema="accounting")
