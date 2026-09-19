"""alter marketing.campaigns: add template_id

Revision ID: 0022_campaigns_template_id
Revises: 0021_marketing_templates
Create Date: 2026-09-21 00:00:08.000000

docs/ROADMAP.md Phase 6.4. `template_id` is nullable (a campaign need not
be created from a template) and, once set, is a one-time copy-in at
campaign creation/update time -- `product/marketing/campaigns.py` copies
`content` into `body` (and `subject`, for email templates) when
`template_id` is supplied; it is NOT a live reference re-read at send
time (editing a template later must not retroactively change an
already-drafted campaign's own stored body -- see
`product/marketing/campaigns.py`'s own docstring for this explicit
semantics decision). Composite FK, column-scoped `ON DELETE SET NULL
(template_id)` -- deleting a template must not delete or corrupt
campaigns that used it, only unlink the reference; the campaign's own
already-copied `body`/`subject` are unaffected either way. This is the
correct pattern established since the deferred Phase 4 CRM bug's
discovery -- never a bare, unscoped `SET NULL` on a multi-column FK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_campaigns_template_id"
down_revision: str | Sequence[str] | None = "0021_marketing_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns", sa.Column("template_id", sa.Uuid(), nullable=True), schema="marketing"
    )
    op.create_index(
        "ix_marketing_campaigns_template_id", "campaigns", ["template_id"], schema="marketing"
    )
    op.create_foreign_key(
        "fk_marketing_campaigns_tenant_template",
        "campaigns",
        "templates",
        ["tenant_id", "template_id"],
        ["tenant_id", "id"],
        source_schema="marketing",
        referent_schema="marketing",
        ondelete="SET NULL (template_id)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_marketing_campaigns_tenant_template",
        "campaigns",
        schema="marketing",
        type_="foreignkey",
    )
    op.drop_index("ix_marketing_campaigns_template_id", table_name="campaigns", schema="marketing")
    op.drop_column("campaigns", "template_id", schema="marketing")
