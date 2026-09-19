"""create crm.custom_field_definitions and crm.custom_field_values tables

Revision ID: 0010_crm_custom_fields
Revises: 0009_crm_tasks_and_notes
Create Date: 2026-09-20 00:00:06.000000

docs/ROADMAP.md Phase 4.4. A typed key/value split (definitions + values),
never JSONB with dynamic keys and never a dynamically-named column -- the
roadmap's own explicit injection-safety requirement ("no dynamic SQL from
tenant-supplied field names"). `custom_field_values` carries the same
three-nullable-composite-FK-plus-exactly-one-CHECK shape 0009 already
established for tasks/notes, plus its own `field_definition_id` composite
FK, both ON DELETE CASCADE (product/crm/models.py's own module docstring).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0010_crm_custom_fields"
down_revision: str | Sequence[str] | None = "0009_crm_tasks_and_notes"
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
        "custom_field_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_custom_field_definitions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "name",
            name="uq_crm_custom_field_definitions_tenant_entity_name",
        ),
        schema="crm",
    )
    op.create_index(
        "ix_crm_custom_field_definitions_tenant_id",
        "custom_field_definitions",
        ["tenant_id"],
        schema="crm",
    )
    for statement in tenant_rls_statements("custom_field_definitions", schema="crm"):
        op.execute(statement)
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.custom_field_definitions TO "{app_role}"'
    )

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("field_definition_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_custom_field_values_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "field_definition_id",
            "contact_id",
            "company_id",
            "opportunity_id",
            name="uq_crm_custom_field_values_one_per_entity",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "field_definition_id"],
            ["crm.custom_field_definitions.tenant_id", "crm.custom_field_definitions.id"],
            name="fk_crm_custom_field_values_tenant_definition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_custom_field_values_tenant_contact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_custom_field_values_tenant_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_custom_field_values_tenant_opportunity",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            _EXACTLY_ONE_ENTITY_SQL, name="ck_crm_custom_field_values_exactly_one_entity"
        ),
        schema="crm",
    )
    for col in ("tenant_id", "contact_id", "company_id", "opportunity_id"):
        op.create_index(
            f"ix_crm_custom_field_values_{col}", "custom_field_values", [col], schema="crm"
        )
    for statement in tenant_rls_statements("custom_field_values", schema="crm"):
        op.execute(statement)
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.custom_field_values TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("custom_field_values", schema="crm")
    op.drop_table("custom_field_definitions", schema="crm")
