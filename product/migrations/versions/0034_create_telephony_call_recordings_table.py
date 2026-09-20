"""create telephony.call_recordings table

Revision ID: 0034_telephony_call_recordings
Revises: 0033_telephony_call_events
Create Date: 2026-09-20 00:00:04.000000

docs/ROADMAP.md Phase 8.3. Metadata-only -- the recording bytes
themselves live in `product.foundation.storage.ObjectStorage` (Protocol +
Fake, no real vendor selected this phase), `storage_key` is the pointer.
`ON DELETE CASCADE` on `call_id` -- a recording has no meaning without its
parent call. `retention_expires_at` is `NOT NULL`: every recording
carries a retention window from the moment it is stored, per this phase's
own "retention is mandatory, not optional" requirement
(`product/telephony/recordings.py::purge_expired_recordings()` is the
enforcement).

**No route exposes this table at all** -- see
`product/telephony/__init__.py`'s own module docstring on Phase 8.3's
"dedicated security review" gate. `telephony.call_recording` is also its
own, separate RBAC resource (`product/telephony/permissions.py`), never
implied by `telephony.call:read`.
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from infra.db.rls import tenant_rls_statements

revision: str = "0034_telephony_call_recordings"
down_revision: str | Sequence[str] | None = "0033_telephony_call_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_APP_ROLE = "product_app"


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", _DEFAULT_APP_ROLE)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise ValueError(f"APP_DB_USER must be a plain SQL identifier, got: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "call_recordings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("core.tenants.id"), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_telephony_call_recordings_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["telephony.calls.tenant_id", "telephony.calls.id"],
            name="fk_telephony_call_recordings_tenant_call",
            ondelete="CASCADE",
        ),
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_call_recordings_tenant_id",
        "call_recordings",
        ["tenant_id"],
        schema="telephony",
    )
    op.create_index(
        "ix_telephony_call_recordings_call_id",
        "call_recordings",
        ["call_id"],
        schema="telephony",
    )

    for statement in tenant_rls_statements("call_recordings", schema="telephony"):
        op.execute(statement)

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON telephony.call_recordings TO "{_app_role()}"'
    )


def downgrade() -> None:
    op.drop_table("call_recordings", schema="telephony")
