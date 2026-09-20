"""Inbound call routing policy (docs/ROADMAP.md Phase 8.2).

**The defined routing policy**: least-recently-assigned round robin over
`phone_number_id`'s own configured, ordered `PhoneNumberRoutingTarget`
list -- whichever configured target user has gone longest without being
assigned a call on this number (ties broken by ascending `position`, then
an unassigned target beats any target with a prior assignment) receives
the next inbound call. Deliberately **not** a persisted cursor column on
`PhoneNumber` (which is NOT RLS-scoped, see `product/telephony/models.py`'s
own module docstring) -- computing the decision directly from `Call.
assigned_user_id`/`created_at` (ordinary RLS-scoped data, already reached
via `tenant_session_scope()`) avoids ever needing a second transaction
against the unscoped table for a value that changes on every single
routed call. This is a real, deterministic, testable policy -- not a
stand-in for a future "real" one.

**Concurrency**: the routing-target rows for `phone_number_id` are locked
(`with_for_update()`) for the duration of the decision -- two concurrent
inbound calls to the *same* number are serialized here exactly like
`product/appointments/booking.py`'s own row-lock discipline for
cancel/reschedule races, so they cannot compute the identical "least
recently assigned" target and both receive it.

Returns `None` (unrouted) if `phone_number_id` has no configured routing
targets at all -- a real, disclosed, deliberately un-escalated outcome
(this phase ships no queue/voicemail fallback for an unrouted call; see
`product/telephony/calls.py`'s own module docstring).
"""

from __future__ import annotations

import uuid

from infra.db import select

from product.telephony.models import Call, PhoneNumberRoutingTarget


def route_inbound_call(
    session, tenant_id: uuid.UUID, phone_number_id: uuid.UUID
) -> uuid.UUID | None:
    """Must be called with an already-open `tenant_session_scope(tenant_id)`
    session -- this function issues no session/transaction of its own, so
    its lock and the caller's own `Call` insert commit atomically together
    (mirrors `product/appointments/booking.py::_locked_appointment_for_manage_token()`'s
    identical "caller owns the transaction" shape)."""
    targets = (
        session.execute(
            select(PhoneNumberRoutingTarget)
            .where(
                PhoneNumberRoutingTarget.tenant_id == tenant_id,
                PhoneNumberRoutingTarget.phone_number_id == phone_number_id,
            )
            .order_by(PhoneNumberRoutingTarget.position.asc())
            .with_for_update()
        )
        .scalars()
        .all()
    )
    if not targets:
        return None

    last_assigned_at: dict[uuid.UUID, object] = {}
    for target in targets:
        row = session.execute(
            select(Call.created_at)
            .where(
                Call.tenant_id == tenant_id,
                Call.phone_number_id == phone_number_id,
                Call.assigned_user_id == target.user_id,
            )
            .order_by(Call.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        last_assigned_at[target.user_id] = row

    def _sort_key(target: PhoneNumberRoutingTarget) -> tuple[int, object, int]:
        last = last_assigned_at[target.user_id]
        # Never-assigned (None) sorts before any real timestamp;
        # position is the final tie-break.
        return (0 if last is None else 1, last, target.position)

    chosen = min(targets, key=_sort_key)
    return chosen.user_id


__all__ = ["route_inbound_call"]
