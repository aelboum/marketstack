"""add telephony.calls.active_transfer_attempt_id

Revision ID: 0066_transfer_attempt_id
Revises: 0065_human_transfer_dest
Create Date: 2026-09-29 00:00:02.000000

Phase 27.0 HIGH-1 remediation (post-implementation security audit). The
minimum persistent primitive required to make attended-transfer side
effects (`create_consultation_leg()`/`bridge_call()`) atomically
ownership-gated rather than merely status-gated: a nullable
`active_transfer_attempt_id` on the existing `Call` row, set exactly once
when a transfer attempt is atomically claimed
(`product/telephony/calls.py::try_start_transfer_attempt()`), and cleared
exactly once when that attempt is consumed for bridging
(`try_consume_transfer_attempt_for_bridge()`) or closed by failure
(`apply_call_transfer_event()`'s own attempt-clearing behavior). This is
the narrowly-scoped, database-native mechanism this remediation uses
instead of a distributed lock -- no Redis locking, no new lock table; the
existing `with_for_update()` row-lock discipline every other telephony
state transition already uses is what makes the claim/consume atomic.

Nullable, no default beyond `NULL` -- a call with no transfer ever
attempted, or between transfer attempts, simply has no active attempt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_transfer_attempt_id"
down_revision: str | Sequence[str] | None = "0065_human_transfer_dest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "calls"
_SCHEMA = "telephony"
_COLUMN = "active_transfer_attempt_id"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(_TABLE, _COLUMN, schema=_SCHEMA)
