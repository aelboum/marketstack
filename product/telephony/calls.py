"""Call lifecycle: outbound placement, inbound provider-event processing,
routing, and read access (docs/ROADMAP.md Phase 8.2).

**The explicit call state machine** -- never a bare, unconstrained
`status` write. `_ALLOWED_TRANSITIONS` below is the complete, authoritative
transition table:

```
ringing     -> in_progress   (answered)
ringing     -> no_answer     (timed out / rejected before connect)
ringing     -> failed        (provider/system error before connect)
in_progress -> completed     (normal hangup)
in_progress -> failed        (dropped/error mid-call)
```

`completed`/`no_answer`/`failed` are terminal (`product/telephony/models.py
::TERMINAL_CALL_STATUSES`) -- no transition out of any of them is ever
valid. A request to move a call to its **own current status** is treated
as an idempotent no-op (the identical provider event delivered twice
after the first one already applied it), never
`TelephonyInvalidStateTransitionError` -- that error is reserved for a
transition genuinely not in the table above (e.g. `completed ->
in_progress`, or an out-of-order `ringing` event arriving after
`in_progress` already applied). This distinction is what "duplicate
events" vs. "out-of-order events" concretely means here: the former is
silently accepted (same status, same effect), the latter is rejected loud
(a real bug/replay/attack signal, not swallowed).

**Concurrency**: every transition is applied under
`session.get(Call, id, with_for_update=True)` -- the identical row-lock
discipline `product/appointments/booking.py`'s own cancel/reschedule races
already use. Two concurrent provider events for the same call are
serialized by Postgres's own row lock, never a Python-level lock.

**Idempotency/replay protection for inbound provider events** --
`receive_inbound_call_event()` performs a real database-enforced
`CallEvent` insert (`UniqueConstraint(tenant_id, provider_name,
provider_event_id)`) and translates the resulting `IntegrityError` into a
no-op return, never a "check then insert" as its own guarantee (mirrors
`product/appointments/booking.py`'s identical `EXCLUDE`-constraint
discipline for double-booking).

**Tenant resolution never trusts the event payload** -- `to_number` is
looked up against `PhoneNumber` (untenanted, see
`product/telephony/numbers.py`'s own docstring) to discover the real
`tenant_id`; there is no `tenant_id` parameter on
`receive_inbound_call_event()` at all, structurally preventing a caller
from supplying one.

**Signature verification happens before any database read/write** --
`provider.verify_webhook_signature()` is checked first; a failure raises
`TelephonyWebhookSignatureInvalidError` immediately, per
`docs/INTEGRATIONS.md` "Webhook Security."

**Caller-ID-to-contact matching is a disclosed, deferred gap** -- see
`product/telephony/__init__.py`'s own module docstring: no CRM function
resolves a contact by phone number today. `Call.contact_id` is always
`None` for calls created by this module in this pass.

**No queue/voicemail fallback for an unrouted inbound call** -- if
`product/telephony/routing.py::route_inbound_call()` returns `None` (no
routing targets configured), the call is still created and tracked
(`assigned_user_id = None`), never rejected/dropped -- a real, disclosed
simplification, not a silent failure.

`_process_inbound_event()` publishes `telephony.call.completed` the
instant a call actually reaches `STATUS_COMPLETED` (docs/ROADMAP.md
Phase 10.2's own trigger library) -- a single, additive `publish()` call
added in this phase, mirroring `product/crm/opportunities.py
::change_stage()`'s own precedent; no other transition/status behavior
in this module changed for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, session_scope, tenant_session_scope

from product.foundation.events import Event, publish
from product.telephony.errors import (
    TelephonyInvalidStateTransitionError,
    TelephonyProviderError,
    TelephonyReferenceNotFoundError,
    TelephonyUnknownNumberError,
    TelephonyValidationError,
    TelephonyWebhookSignatureInvalidError,
)
from product.telephony.models import (
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_NO_ANSWER,
    STATUS_RINGING,
    TERMINAL_CALL_STATUSES,
    Call,
    CallEvent,
    PhoneNumber,
)
from product.telephony.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.telephony.permissions import CALL_RESOURCE, require
from product.telephony.provider import TelephonyProvider
from product.telephony.routing import route_inbound_call

CALL_COMPLETED_EVENT_TYPE = "telephony.call.completed"
CALL_COMPLETED_EVENT_VERSION = 1

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_RINGING: frozenset({STATUS_IN_PROGRESS, STATUS_NO_ANSWER, STATUS_FAILED}),
    STATUS_IN_PROGRESS: frozenset({STATUS_COMPLETED, STATUS_FAILED}),
    STATUS_COMPLETED: frozenset(),
    STATUS_NO_ANSWER: frozenset(),
    STATUS_FAILED: frozenset(),
}

# Inbound provider event type -> resulting call status. A real adapter's
# own event names would differ per vendor; this is *a* real, working
# vocabulary (mirrors product/telephony/provider.py's own "real scheme,
# not a specific vendor's" reasoning), proving the transition/idempotency
# pipeline end-to-end.
EVENT_CALL_INITIATED = "call.initiated"
EVENT_CALL_ANSWERED = "call.answered"
EVENT_CALL_COMPLETED = "call.completed"
EVENT_CALL_NO_ANSWER = "call.no_answer"
EVENT_CALL_FAILED = "call.failed"

_EVENT_TO_STATUS: dict[str, str] = {
    EVENT_CALL_ANSWERED: STATUS_IN_PROGRESS,
    EVENT_CALL_COMPLETED: STATUS_COMPLETED,
    EVENT_CALL_NO_ANSWER: STATUS_NO_ANSWER,
    EVENT_CALL_FAILED: STATUS_FAILED,
}


@dataclass(frozen=True, slots=True)
class CallView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone_number_id: uuid.UUID
    provider_name: str
    provider_call_id: str | None
    direction: str
    from_number: str
    to_number: str
    status: str
    contact_id: uuid.UUID | None
    assigned_user_id: uuid.UUID | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: Call) -> CallView:
    return CallView(
        id=row.id,
        tenant_id=row.tenant_id,
        phone_number_id=row.phone_number_id,
        provider_name=row.provider_name,
        provider_call_id=row.provider_call_id,
        direction=row.direction,
        from_number=row.from_number,
        to_number=row.to_number,
        status=row.status,
        contact_id=row.contact_id,
        assigned_user_id=row.assigned_user_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_transition(row: Call, requested_status: str, *, at: datetime) -> None:
    """Mutates `row` in place. Caller holds the row lock and owns the
    transaction (mirrors `product/telephony/routing.py::route_inbound_call()`'s
    identical "caller owns the transaction" shape)."""
    if requested_status == row.status:
        return  # idempotent no-op -- see module docstring.
    allowed = _ALLOWED_TRANSITIONS.get(row.status, frozenset())
    if requested_status not in allowed:
        raise TelephonyInvalidStateTransitionError(
            row.id, current_status=row.status, requested_status=requested_status
        )
    row.status = requested_status
    if requested_status == STATUS_IN_PROGRESS:
        row.started_at = at
    elif requested_status in TERMINAL_CALL_STATUSES:
        row.ended_at = at


def get_call(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, call_id: uuid.UUID) -> CallView:
    require(actor_user_id, tenant_id, resource=CALL_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Call, call_id)
        if row is None or row.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("call", call_id)
        session.expunge(row)
    return _to_view(row)


def list_calls(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    direction: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CallView]:
    require(actor_user_id, tenant_id, resource=CALL_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    query = select(Call).where(Call.tenant_id == tenant_id)
    if status is not None:
        query = query.where(Call.status == status)
    if direction is not None:
        query = query.where(Call.direction == direction)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                query.order_by(Call.created_at.desc()).limit(bounded_limit).offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def initiate_outbound_call(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: uuid.UUID,
    to_number: str,
    provider: TelephonyProvider,
) -> CallView:
    """No default `provider` -- see module docstring/`product/telephony
    /__init__.py`. The `Call` row is created first (`ringing`), then
    `provider.place_call()` is attempted; a provider failure transitions
    the same row to `failed` (never left dangling in `ringing`) before
    re-raising -- the caller sees both the real exception and a call
    history row that accurately reflects what happened, mirroring this
    phase's own "provider failures must fail safely" requirement."""
    require(actor_user_id, tenant_id, resource=CALL_RESOURCE, action="create")
    if not to_number:
        raise TelephonyValidationError("to_number must not be empty.")

    with session_scope() as lookup_session:
        phone_number = lookup_session.get(PhoneNumber, phone_number_id)
        if phone_number is None or phone_number.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("phone_number", phone_number_id)
        from_number = phone_number.phone_number

    with tenant_session_scope(tenant_id) as session:
        row = Call(
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            provider_name=provider.name,
            direction=DIRECTION_OUTBOUND,
            from_number=from_number,
            to_number=to_number,
            status=STATUS_RINGING,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        call_id = row.id

    try:
        placed = provider.place_call(from_number=from_number, to_number=to_number)
    except TelephonyProviderError:
        with tenant_session_scope(tenant_id) as session:
            row = session.get(Call, call_id, with_for_update=True)
            assert row is not None  # just created above, in this same tenant
            _apply_transition(row, STATUS_FAILED, at=_now())
            session.flush()
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="telephony.call.outbound_failed",
            resource_type="telephony.call",
            resource_id=str(call_id),
            outcome=AuditOutcome.FAILURE,
        )
        raise

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Call, call_id, with_for_update=True)
        assert row is not None  # just created above, in this same tenant
        row.provider_call_id = placed.provider_call_id
        session.flush()
        session.refresh(row)
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.call.initiate_outbound",
        resource_type="telephony.call",
        resource_id=str(call_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"phone_number_id": str(phone_number_id)},
    )
    return _to_view(row)


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


def _resolve_phone_number(to_number: str) -> PhoneNumber | None:
    with session_scope() as session:
        row = session.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == to_number)
        ).scalar_one_or_none()
        if row is None:
            return None
        session.expunge(row)
        return row


def receive_inbound_call_event(
    *,
    provider: TelephonyProvider,
    headers: dict[str, str],
    body: bytes,
    provider_event_id: str,
    event_type: str,
    to_number: str,
    from_number: str,
    provider_call_id: str,
    now: datetime | None = None,
) -> CallView | None:
    """The future real webhook receiver's own entrypoint (mirrors
    `saas-os` `core.webhooks`'s own P1.10 "primitives a future receiver
    would call, never the receiver itself" precedent) -- see module
    docstring for the full pipeline. Returns `None` for a duplicate
    delivery (already processed) or an unknown `event_type` (recorded for
    idempotency, but no state change) -- never raises for either, since
    neither is a real error from the provider's own perspective.
    """
    if not provider.verify_webhook_signature(headers=headers, body=body):
        raise TelephonyWebhookSignatureInvalidError(
            f"signature verification failed for provider {provider.name!r}."
        )

    phone_number = _resolve_phone_number(to_number)
    if phone_number is None:
        raise TelephonyUnknownNumberError(f"no phone number provisioned for {to_number!r}.")
    tenant_id = phone_number.tenant_id
    current = now if now is not None else _now()

    return _process_inbound_event(
        tenant_id=tenant_id,
        phone_number_id=phone_number.id,
        provider=provider,
        provider_event_id=provider_event_id,
        event_type=event_type,
        to_number=to_number,
        from_number=from_number,
        provider_call_id=provider_call_id,
        current=current,
    )


def _process_inbound_event(
    *,
    tenant_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    provider: TelephonyProvider,
    provider_event_id: str,
    event_type: str,
    to_number: str,
    from_number: str,
    provider_call_id: str,
    current: datetime,
) -> CallView | None:
    with tenant_session_scope(tenant_id) as session:
        existing_call = session.execute(
            select(Call).where(
                Call.tenant_id == tenant_id,
                Call.provider_name == provider.name,
                Call.provider_call_id == provider_call_id,
            )
        ).scalar_one_or_none()

        if event_type == EVENT_CALL_INITIATED:
            if existing_call is not None:
                _record_event_idempotently(
                    session,
                    tenant_id,
                    existing_call.id,
                    provider.name,
                    provider_event_id,
                    event_type,
                )
                session.expunge(existing_call)
                return _to_view(existing_call)
            call = Call(
                tenant_id=tenant_id,
                phone_number_id=phone_number_id,
                provider_name=provider.name,
                provider_call_id=provider_call_id,
                direction=DIRECTION_INBOUND,
                from_number=from_number,
                to_number=to_number,
                status=STATUS_RINGING,
            )
            try:
                with session.begin_nested():
                    session.add(call)
                    session.flush()
            except IntegrityError:
                # A concurrent duplicate delivery raced us and won the
                # partial unique index on (tenant_id, provider_name,
                # provider_call_id) -- only this savepoint is rolled back
                # (nothing else has been written yet in this transaction);
                # re-fetch the winner's row rather than surfacing a raw
                # IntegrityError for what is, from either caller's
                # perspective, a successful idempotent call.initiated.
                winner = session.execute(
                    select(Call).where(
                        Call.tenant_id == tenant_id,
                        Call.provider_name == provider.name,
                        Call.provider_call_id == provider_call_id,
                    )
                ).scalar_one()
                _record_event_idempotently(
                    session, tenant_id, winner.id, provider.name, provider_event_id, event_type
                )
                session.expunge(winner)
                return _to_view(winner)
            assigned = route_inbound_call(session, tenant_id, phone_number_id)
            if assigned is not None:
                call.assigned_user_id = assigned
            session.flush()
            _record_event_idempotently(
                session, tenant_id, call.id, provider.name, provider_event_id, event_type
            )
            session.refresh(call)
            session.expunge(call)
            call_id_for_audit = call.id
            view = _to_view(call)
        else:
            target_status = _EVENT_TO_STATUS.get(event_type)
            if existing_call is None:
                # A status-update event for a call we never saw
                # call.initiated for (out-of-order/unknown-call delivery).
                # No row exists to attach a CallEvent to (call_id is NOT
                # NULL) -- there is nothing to persist and nothing to
                # transition; no error, per module docstring.
                return None
            call = session.get(Call, existing_call.id, with_for_update=True)
            assert call is not None  # existing_call was just found by this same query
            recorded = _record_event_idempotently(
                session, tenant_id, call.id, provider.name, provider_event_id, event_type
            )
            if not recorded:
                session.expunge(call)
                return _to_view(call)
            if target_status is not None:
                _apply_transition(call, target_status, at=current)
                session.flush()
            session.refresh(call)
            session.expunge(call)
            call_id_for_audit = call.id
            view = _to_view(call)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action="telephony.call.inbound_event",
        resource_type="telephony.call",
        resource_id=str(call_id_for_audit),
        outcome=AuditOutcome.SUCCESS,
        metadata={"event_type": event_type},
    )
    if view is not None and view.status == STATUS_COMPLETED:
        publish(
            Event(
                type=CALL_COMPLETED_EVENT_TYPE,
                version=CALL_COMPLETED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"call_id": str(view.id)},
            )
        )
    return view


def _record_event_idempotently(
    session: Any,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    provider_name: str,
    provider_event_id: str,
    event_type: str,
) -> bool:
    """Returns `True` if this call actually recorded the event (first
    delivery), `False` if it was already recorded (duplicate -- caller
    must not reapply the transition).

    **Uses a `SAVEPOINT` (`session.begin_nested()`), never a full
    `session.rollback()`** -- this is called from deep inside a larger
    transaction that may already hold other uncommitted writes (the new
    `Call` row and its routing assignment, for `call.initiated`); a plain
    `rollback()` on a duplicate-event `IntegrityError` would discard that
    earlier work too. Only the nested savepoint -- this one insert -- is
    undone on conflict."""
    try:
        with session.begin_nested():
            session.add(
                CallEvent(
                    tenant_id=tenant_id,
                    call_id=call_id,
                    provider_name=provider_name,
                    provider_event_id=provider_event_id,
                    event_type=event_type,
                )
            )
            session.flush()
        return True
    except IntegrityError:
        return False


__all__ = [
    "CallView",
    "EVENT_CALL_ANSWERED",
    "EVENT_CALL_COMPLETED",
    "EVENT_CALL_FAILED",
    "EVENT_CALL_INITIATED",
    "EVENT_CALL_NO_ANSWER",
    "get_call",
    "initiate_outbound_call",
    "list_calls",
    "receive_inbound_call_event",
]
