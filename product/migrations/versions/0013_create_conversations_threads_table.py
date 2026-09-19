"""create conversations.threads table

Revision ID: 0013_conversations_threads
Revises: 0012_crm_import_jobs
Create Date: 2026-09-21 00:00:00.000000

docs/ROADMAP.md Phase 5.1. First table in the `conversations` schema --
creates the schema itself (mirrors crm.companies' own 0004 migration:
the migration that creates the schema is also the one whose downgrade
drops it). `contact_id` is a composite FK into `crm.contacts` -- this
migration therefore depends on the `crm` schema/table already existing
(0004/0005, already applied by the time this runs). `ON DELETE SET NULL`
on `contact_id` -- deleting a contact must not destroy conversation
history, only unlink it (product/conversations/models.py's own module
docstring has the full reasoning). `assigned_to_user_id` is a plain
(non-composite) FK into the global `core.users` table.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0013_conversations_threads"
down_revision: str | Sequence[str] | None = "0012_crm_import_jobs"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS conversations")
    op.create_table(
        "threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("assigned_to_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_threads_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_conversations_threads_tenant_contact",
            # Column-scoped SET NULL -- see product/conversations/models.py's
            # own module docstring / the identical comment on this same
            # constraint there for the full reasoning (a real bug found
            # empirically: bare "SET NULL" on a multi-column FK nulls out
            # every FK column, including the NOT NULL tenant_id).
            ondelete="SET NULL (contact_id)",
        ),
        schema="conversations",
    )
    op.create_index(
        "ix_conversations_threads_tenant_id", "threads", ["tenant_id"], schema="conversations"
    )
    op.create_index(
        "ix_conversations_threads_contact_id", "threads", ["contact_id"], schema="conversations"
    )
    op.create_index(
        "ix_conversations_threads_assigned_to_user_id",
        "threads",
        ["assigned_to_user_id"],
        schema="conversations",
    )

    for statement in tenant_rls_statements("threads", schema="conversations"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA conversations TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON conversations.threads TO "{app_role}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA conversations "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA conversations "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("threads", schema="conversations")
    op.execute("DROP SCHEMA IF EXISTS conversations")
