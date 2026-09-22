"""add assigned_user_id to crm.opportunities

Revision ID: 0049_crm_opp_assigned_user
Revises: 0048_templates_snapshots
Create Date: 2026-09-22 00:00:00.000000

docs/ROADMAP.md Phase 22 ("Lead Capture & Qualification Loop"), scope item
(c): a plain nullable FK to `core.users.id` -- not composite, since
`core.users` has no `tenant_id` column to compose against, mirroring
`product/websites/models.py::Website.created_by_user_id`'s identical
shape. No RLS change (RLS policies are defined on the table, not per
column); no new foreign key against any product-owned table. `NULL` means
"unassigned" -- the pre-Phase-22 state every existing opportunity is
already in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_crm_opp_assigned_user"  # <=32 chars: alembic_version.version_num's limit
down_revision: str | Sequence[str] | None = "0048_templates_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "opportunities",
        sa.Column(
            "assigned_user_id",
            sa.Uuid(),
            sa.ForeignKey("core.users.id"),
            nullable=True,
        ),
        schema="crm",
    )
    op.create_index(
        "ix_crm_opportunities_assigned_user_id",
        "opportunities",
        ["assigned_user_id"],
        schema="crm",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_opportunities_assigned_user_id",
        table_name="opportunities",
        schema="crm",
    )
    op.drop_column("opportunities", "assigned_user_id", schema="crm")
