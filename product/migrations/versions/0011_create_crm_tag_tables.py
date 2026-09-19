"""create crm.tags and crm.entity_tags tables

Revision ID: 0011_crm_tags
Revises: 0010_crm_custom_fields
Create Date: 2026-09-20 00:00:07.000000

docs/ROADMAP.md Phase 4.4. `entity_tags` carries the same
three-nullable-composite-FK-plus-exactly-one-CHECK shape as tasks/notes/
custom_field_values, plus its own `tag_id` composite FK, both ON DELETE
CASCADE. `uq_crm_entity_tags_tag_per_entity` prevents attaching the same
tag twice to the same entity.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0011_crm_tags"
down_revision: str | Sequence[str] | None = "0010_crm_custom_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"

_EXACTLY_ONE_ENTITY_SQL = (
    "(CASE WHEN contact_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN company_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN opportunity_id IS NOT NULL THEN 1 ELSE 0 END) = 1"
)


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    app_role = _app_role()

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_tags_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_crm_tags_tenant_name"),
        schema="crm",
    )
    op.create_index("ix_crm_tags_tenant_id", "tags", ["tenant_id"], schema="crm")
    for statement in tenant_rls_statements("tags", schema="crm"):
        op.execute(statement)
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.tags TO "{app_role}"')

    op.create_table(
        "entity_tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_entity_tags_tenant_id_id"),
        sa.UniqueConstraint(
            "tag_id",
            "contact_id",
            "company_id",
            "opportunity_id",
            name="uq_crm_entity_tags_tag_per_entity",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tag_id"],
            ["crm.tags.tenant_id", "crm.tags.id"],
            name="fk_crm_entity_tags_tenant_tag",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_entity_tags_tenant_contact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_entity_tags_tenant_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_entity_tags_tenant_opportunity",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_EXACTLY_ONE_ENTITY_SQL, name="ck_crm_entity_tags_exactly_one_entity"),
        schema="crm",
    )
    for col in ("tenant_id", "tag_id", "contact_id", "company_id", "opportunity_id"):
        op.create_index(f"ix_crm_entity_tags_{col}", "entity_tags", [col], schema="crm")
    for statement in tenant_rls_statements("entity_tags", schema="crm"):
        op.execute(statement)
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.entity_tags TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("entity_tags", schema="crm")
    op.drop_table("tags", schema="crm")
