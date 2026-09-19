"""marketing tracking: campaigns.click_target_url, campaign_recipients
open/click columns, and a new, deliberately unscoped
recipient_tracking_tokens lookup table

Revision ID: 0023_marketing_tracking
Revises: 0022_campaigns_template_id
Create Date: 2026-09-21 00:00:09.000000

docs/ROADMAP.md Phase 6.5 (tracking and segmentation refinement).

`marketing.campaigns.click_target_url` -- the ONE call-to-action URL a
campaign's tracked click link points to (validated http/https-only,
server-side, at campaign create/update time). This phase deliberately
tracks one link per campaign, not arbitrary multi-link click tracking
within a message body (that would need a real link-rewriting mechanism --
parsing the body, substituting every URL -- meaningfully more complex
than the roadmap's own acceptance criterion, "opens/clicks are recorded
and usable in segmentation," actually requires). A disclosed scope
boundary, not a silent narrowing -- see
`product/marketing/routes.py`'s tracking-endpoint docstrings for the
full security reasoning (the click-tracking redirect target is always
and only this server-stored column, never a caller-supplied query
parameter -- this is what makes the endpoint immune to being used as an
open-redirect gadget).

`marketing.campaign_recipients.opened_at`/`clicked_at` -- nullable, set
only once (first-open/first-click wins, idempotent -- a real email client
typically fetches a tracking pixel more than once). Ordinary columns on
the existing, RLS-protected table, written through the normal
`tenant_session_scope()` path once the recipient has been resolved.

**`marketing.recipient_tracking_tokens` -- a new, separate, deliberately
UNSCOPED table, NOT a `tracking_token` column on `campaign_recipients`
itself.** `campaign_recipients` carries RLS (migration 0018) -- a plain,
untenanted `session_scope()` read against an RLS-protected table returns
zero rows regardless of the query, so a public tracking pixel/click
request (which must resolve a token to a tenant/recipient *before* any
tenant context exists) could never look up a `tracking_token` column
stored directly on that table. This mirrors exactly why
`white_label.tenant_domains` is its own small, separate, unscoped table
rather than an unscoped column bolted onto `core.tenants` itself
(migration 0003) -- the identical shape, applied here: a thin, unscoped
mapping table (`tracking_token` -> `tenant_id`, `recipient_id`) resolved
via `session_scope()`, after which the real recipient row is read/written
through the ordinary, correctly-RLS-enforced `tenant_session_scope()`
path exactly as every other write in this product is. `ON DELETE CASCADE`
on `recipient_id` -- a tracking token has no independent meaning once its
recipient row is gone (mirrors `campaign_recipients.campaign_id`'s own
`CASCADE` reasoning).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_marketing_tracking"
down_revision: str | Sequence[str] | None = "0022_campaigns_template_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("click_target_url", sa.String(length=2048), nullable=True),
        schema="marketing",
    )

    op.add_column(
        "campaign_recipients",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        schema="marketing",
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        schema="marketing",
    )

    # Deliberately NO tenant_rls_statements() call for this table -- see
    # module docstring. GRANT only, mirroring white_label.tenant_domains'
    # own migration exactly.
    op.create_table(
        "recipient_tracking_tokens",
        sa.Column("tracking_token", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["marketing.campaign_recipients.tenant_id", "marketing.campaign_recipients.id"],
            name="fk_marketing_recipient_tracking_tokens_tenant_recipient",
            ondelete="CASCADE",
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_recipient_tracking_tokens_recipient_id",
        "recipient_tracking_tokens",
        ["recipient_id"],
        schema="marketing",
    )

    app_role = _app_role()
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON marketing.recipient_tracking_tokens "
        f'TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("recipient_tracking_tokens", schema="marketing")
    op.drop_column("campaign_recipients", "clicked_at", schema="marketing")
    op.drop_column("campaign_recipients", "opened_at", schema="marketing")
    op.drop_column("campaigns", "click_target_url", schema="marketing")


def _app_role() -> str:
    import os
    import re

    role = os.environ.get("APP_DB_USER", "product_app")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role
