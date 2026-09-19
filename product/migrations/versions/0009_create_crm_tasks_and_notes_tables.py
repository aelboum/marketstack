"""create crm.tasks and crm.notes tables

Revision ID: 0009_crm_tasks_and_notes
Revises: 0008_crm_opportunities
Create Date: 2026-09-20 00:00:05.000000

docs/ROADMAP.md Phase 4.3. Both tables carry three nullable composite
FKs (contact_id/company_id/opportunity_id) plus a CHECK constraint
requiring exactly one to be set -- real referential integrity for a
"attached to one of three entity types" relationship, never an untyped
entity_type/entity_id pair with no FK. All three ON DELETE CASCADE
(product/crm/models.py's own module docstring: a task/note has no
independent meaning without its one required parent).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0009_crm_tasks_and_notes"
down_revision: str | Sequence[str] | None = "0008_crm_opportunities"
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


def _entity_fk_columns() -> list[sa.Column]:
    return [
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
    ]


def _entity_fk_constraints(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name=f"fk_crm_{table}_tenant_contact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name=f"fk_crm_{table}_tenant_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name=f"fk_crm_{table}_tenant_opportunity",
            ondelete="CASCADE",
        ),
    ]


def upgrade() -> None:
    app_role = _app_role()

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        *_entity_fk_columns(),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_tasks_tenant_id_id"),
        *_entity_fk_constraints("tasks"),
        sa.CheckConstraint(_EXACTLY_ONE_ENTITY_SQL, name="ck_crm_tasks_exactly_one_entity"),
        schema="crm",
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        *_entity_fk_columns(),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_notes_tenant_id_id"),
        *_entity_fk_constraints("notes"),
        sa.CheckConstraint(_EXACTLY_ONE_ENTITY_SQL, name="ck_crm_notes_exactly_one_entity"),
        schema="crm",
    )

    for table in ("tasks", "notes"):
        op.create_index(f"ix_crm_{table}_tenant_id", table, ["tenant_id"], schema="crm")
        op.create_index(f"ix_crm_{table}_contact_id", table, ["contact_id"], schema="crm")
        op.create_index(f"ix_crm_{table}_company_id", table, ["company_id"], schema="crm")
        op.create_index(f"ix_crm_{table}_opportunity_id", table, ["opportunity_id"], schema="crm")
        for statement in tenant_rls_statements(table, schema="crm"):
            op.execute(statement)
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON crm.{table} TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("notes", schema="crm")
    op.drop_table("tasks", schema="crm")
