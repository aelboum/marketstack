"""create marketing.campaign_recipients table

Revision ID: 0018_marketing_recipients
Revises: 0017_marketing_suppressions
Create Date: 2026-09-21 00:00:04.000000

docs/ROADMAP.md Phase 6.1's own "records delivery status per recipient"
acceptance criterion. `campaign_id` is a composite FK into
`marketing.campaigns`, `ON DELETE CASCADE` (a recipient row has no
meaning without its campaign). `contact_id` is a composite FK into
`crm.contacts`, **column-scoped** `ON DELETE SET NULL (contact_id)` --
NOT bare `SET NULL`. This is the fix for the exact defect class the
deferred Phase 4 CRM bug demonstrated (bare `SET NULL` on a multi-column
FK nulls every column in the FK, including the `NOT NULL` `tenant_id`,
causing a `NotNullViolation` instead of unlinking) -- see
product/marketing/models.py's own module docstring for the full
reasoning. Schema `marketing` already exists (created by 0016).
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0018_marketing_recipients"
down_revision: str | Sequence[str] | None = "0017_marketing_suppressions"
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
        "campaign_recipients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_marketing_campaign_recipients_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "contact_id",
            name="uq_marketing_campaign_recipients_campaign_contact",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["marketing.campaigns.tenant_id", "marketing.campaigns.id"],
            name="fk_marketing_campaign_recipients_tenant_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_campaign_recipients_tenant_contact",
            # Column-scoped SET NULL -- see module docstring above.
            ondelete="SET NULL (contact_id)",
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_campaign_recipients_tenant_id",
        "campaign_recipients",
        ["tenant_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_campaign_recipients_campaign_id",
        "campaign_recipients",
        ["campaign_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_campaign_recipients_contact_id",
        "campaign_recipients",
        ["contact_id"],
        schema="marketing",
    )

    for statement in tenant_rls_statements("campaign_recipients", schema="marketing"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.campaign_recipients TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("campaign_recipients", schema="marketing")
