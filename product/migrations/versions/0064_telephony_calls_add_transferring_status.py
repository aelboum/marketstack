"""add 'transferring' to telephony.calls status check constraint

Revision ID: 0064_telephony_transferring
Revises: 0063_accounting_payment_allocs
Create Date: 2026-09-29 00:00:00.000000

docs/ROADMAP.md Phase 27.0. `Call.status` gains exactly one new value,
`transferring` -- the minimum state needed to make an in-progress
attended-transfer attempt durable and deterministic (hold caller ->
consultation leg -> human answer -> bridge -> AI exit). A call enters
`transferring` from `in_progress` and always leaves it back to
`in_progress` (successful bridge, or a failed/timed-out transfer's own
approved bounded return-to-AI), or to a genuinely terminal `completed`/
`failed` if the call itself ends while a transfer is in flight (e.g. the
caller hangs up during consultation) -- see
`product/telephony/calls.py::_ALLOWED_TRANSITIONS`'s own updated table.
No other new status is added -- `consulting`/`bridging`/`transferred`/
`voicemail`/`queued` are deliberately not introduced (docs/ROADMAP.md
Phase 27.0's own "do not add speculative states" instruction).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064_telephony_transferring"
down_revision: str | Sequence[str] | None = "0063_accounting_payment_allocs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "calls"
_SCHEMA = "telephony"
_CONSTRAINT_NAME = "ck_telephony_calls_status"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE, schema=_SCHEMA, type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        _TABLE,
        "status IN ('ringing', 'in_progress', 'transferring', 'completed', 'no_answer', 'failed')",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE, schema=_SCHEMA, type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        _TABLE,
        "status IN ('ringing', 'in_progress', 'completed', 'no_answer', 'failed')",
        schema=_SCHEMA,
    )
