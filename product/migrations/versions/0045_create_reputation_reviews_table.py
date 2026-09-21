"""create reputation.reviews table

Revision ID: 0045_reputation_reviews
Revises: 0044_reputation_review_requests
Create Date: 2026-09-21 00:00:03.000000

docs/ROADMAP.md Phase 12.1/12.2. Ordinary RLS-scoped, tenant-owned data.

`review_request_id` is a nullable composite FK into
`reputation.review_requests`, `ON DELETE SET NULL` -- a review is a
standalone fact that must survive the deletion of the request that may
have prompted it; only the link is severed -- see
`product/reputation/models.py::Review`'s own module docstring.

`(tenant_id, provider, external_review_id)` carries a real `UNIQUE`
constraint -- the same review, re-synced from the same provider, must
never be duplicated once a real provider adapter exists (Phase 12.2,
deliberately deferred: `external_review_id` is always `NULL` for a
`'manual'` review today, and Postgres does not consider `NULL` values
equal for `UNIQUE` purposes, so multiple manual reviews never collide on
this constraint).

`provider`/`status` carry real `CheckConstraint`s; `rating` is bounded
`1..5` by `CheckConstraint` -- mirrors `product/appointments/models.py
::AvailabilityRule`'s own bounds-checking precedent.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0045_reputation_reviews"
down_revision: str | Sequence[str] | None = "0044_reputation_review_requests"
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
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("review_request_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("external_review_id", sa.String(length=255), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reputation_reviews_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_request_id"],
            ["reputation.review_requests.tenant_id", "reputation.review_requests.id"],
            name="fk_reputation_reviews_tenant_review_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "external_review_id",
            name="uq_reputation_reviews_tenant_provider_external_id",
        ),
        sa.CheckConstraint("provider IN ('manual')", name="ck_reputation_reviews_provider"),
        sa.CheckConstraint("status IN ('new', 'responded')", name="ck_reputation_reviews_status"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reputation_reviews_rating"),
        schema="reputation",
    )
    op.create_index(
        "ix_reputation_reviews_tenant_id", "reviews", ["tenant_id"], schema="reputation"
    )
    op.create_index(
        "ix_reputation_reviews_review_request_id",
        "reviews",
        ["review_request_id"],
        schema="reputation",
    )

    for statement in tenant_rls_statements("reviews", schema="reputation"):
        op.execute(statement)

    # Table-level GRANT kept explicit despite 0044's `ALTER DEFAULT
    # PRIVILEGES` -- belt-and-suspenders, mirroring `websites.pages`'s own
    # 0043 precedent (that migration's own module docstring does not
    # re-explain this; `websites.websites`'s 0042 default-privileges grant
    # covers future tables the same way this one does).
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON reputation.reviews TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("reviews", schema="reputation")
