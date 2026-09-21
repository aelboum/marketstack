"""create reputation.review_requests table

Revision ID: 0044_reputation_review_requests
Revises: 0043_websites_pages
Create Date: 2026-09-21 00:00:02.000000

docs/ROADMAP.md Phase 12.1. First table in the `reputation` schema --
creates the schema itself, mirroring `websites.websites`'s own 0042
precedent: the migration that creates the schema is also the one whose
downgrade drops it (after 0045/0046's own tables, which depend on this
one, have already been dropped by their own downgrades).

Ordinary RLS-scoped, tenant-owned data (unlike `websites.websites`, this
table needs no untenanted public lookup key, so `tenant_rls_statements()`
applies here, mirroring `websites.pages`'s own 0043 precedent instead).
`contact_id` is a composite FK into `crm.contacts`
(`docs/ADR/0010-reputation-depends-on-crm.md`), `ON DELETE CASCADE` -- a
review request has no meaning without the contact it targets -- see
`product/reputation/models.py::ReviewRequest`'s own module docstring for
why this differs from `appointments.appointments.contact_id`'s own
`SET NULL` choice.

`status`/`channel` carry real `CheckConstraint`s, not only service-layer
validation -- mirrors `product/appointments/models.py
::AvailabilityRule`'s own bounds-checking precedent.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0044_reputation_review_requests"
down_revision: str | Sequence[str] | None = "0043_websites_pages"
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

    op.execute("CREATE SCHEMA IF NOT EXISTS reputation")
    op.create_table(
        "review_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="email"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "requested_by_user_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reputation_review_requests_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_reputation_review_requests_tenant_contact",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'cancelled', 'fulfilled')",
            name="ck_reputation_review_requests_status",
        ),
        sa.CheckConstraint(
            "channel IN ('email')",
            name="ck_reputation_review_requests_channel",
        ),
        schema="reputation",
    )
    op.create_index(
        "ix_reputation_review_requests_tenant_id",
        "review_requests",
        ["tenant_id"],
        schema="reputation",
    )
    op.create_index(
        "ix_reputation_review_requests_contact_id",
        "review_requests",
        ["contact_id"],
        schema="reputation",
    )

    for statement in tenant_rls_statements("review_requests", schema="reputation"):
        op.execute(statement)

    op.execute(f'GRANT USAGE ON SCHEMA reputation TO "{app_role}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON reputation.review_requests TO "{app_role}"'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA reputation "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    app_role = _app_role()

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA reputation "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{app_role}"'
    )
    op.drop_table("review_requests", schema="reputation")
    op.execute("DROP SCHEMA IF EXISTS reputation")
