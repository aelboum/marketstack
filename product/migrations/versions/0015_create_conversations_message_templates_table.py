"""create conversations.message_templates table

Revision ID: 0015_conversations_templates
Revises: 0014_conversations_messages
Create Date: 2026-09-21 00:00:02.000000

docs/ROADMAP.md Phase 5.5. No FK to any other `conversations.*` table --
a template is standalone, literal stored text (no variable-substitution
engine, product/conversations/templates.py's own module docstring).
`channel` is nullable (usable for any channel when unset).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0015_conversations_templates"
down_revision: str | Sequence[str] | None = "0014_conversations_messages"
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
        "message_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_conversations_message_templates_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_conversations_message_templates_tenant_name"
        ),
        schema="conversations",
    )
    op.create_index(
        "ix_conversations_message_templates_tenant_id",
        "message_templates",
        ["tenant_id"],
        schema="conversations",
    )

    for statement in tenant_rls_statements("message_templates", schema="conversations"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON conversations.message_templates TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("message_templates", schema="conversations")
