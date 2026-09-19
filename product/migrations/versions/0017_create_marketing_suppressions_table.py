"""create marketing.suppressions table

Revision ID: 0017_marketing_suppressions
Revises: 0016_marketing_campaigns
Create Date: 2026-09-21 00:00:03.000000

docs/ROADMAP.md Phase 6.1's own "unsubscribe/suppression list honored
before every send" hard-gate requirement. `contact_id` is a composite FK
into `crm.contacts`, `ON DELETE CASCADE` -- a suppression record has no
independent meaning once the contact itself is gone (see
product/marketing/models.py's own module docstring for the open question
this leaves unresolved, deferred to Phase 18). Schema `marketing` already
exists (created by 0016); this migration only adds its own table and
grants to it.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0017_marketing_suppressions"
down_revision: str | Sequence[str] | None = "0016_marketing_campaigns"
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
        "suppressions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_marketing_suppressions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "contact_id",
            "channel",
            name="uq_marketing_suppressions_contact_channel",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_suppressions_tenant_contact",
            ondelete="CASCADE",
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_suppressions_tenant_id", "suppressions", ["tenant_id"], schema="marketing"
    )
    op.create_index(
        "ix_marketing_suppressions_contact_id", "suppressions", ["contact_id"], schema="marketing"
    )

    for statement in tenant_rls_statements("suppressions", schema="marketing"):
        op.execute(statement)

    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.suppressions TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("suppressions", schema="marketing")
