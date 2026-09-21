"""create reputation.review_responses table

Revision ID: 0046_reputation_review_responses
Revises: 0045_reputation_reviews
Create Date: 2026-09-21 00:00:04.000000

docs/ROADMAP.md Phase 12.3. Ordinary RLS-scoped, tenant-owned data.
`review_id` composite-FKs into `reputation.reviews`, `ON DELETE CASCADE`
-- a response has no meaning without the review it responds to, the same
`websites.pages.website_id` shape.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0046_reputation_review_responses"
down_revision: str | Sequence[str] | None = "0045_reputation_reviews"
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
        "review_responses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("posted_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reputation_review_responses_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_id"],
            ["reputation.reviews.tenant_id", "reputation.reviews.id"],
            name="fk_reputation_review_responses_tenant_review",
            ondelete="CASCADE",
        ),
        schema="reputation",
    )
    op.create_index(
        "ix_reputation_review_responses_tenant_id",
        "review_responses",
        ["tenant_id"],
        schema="reputation",
    )
    op.create_index(
        "ix_reputation_review_responses_review_id",
        "review_responses",
        ["review_id"],
        schema="reputation",
    )

    for statement in tenant_rls_statements("review_responses", schema="reputation"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON reputation.review_responses TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("review_responses", schema="reputation")
