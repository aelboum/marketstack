"""Phase 27.0 attended-transfer orchestration (docs/ROADMAP.md Phase 27.0
-- "Twilio Telephony Foundation").

**The approved sequence:**

```
AI
 |
 | hold caller (an adapter-internal detail of leg creation, never a
 |              separate domain operation -- see product/telephony
 |              /provider.py's own module docstring)
 v
create consultation leg  (initiate_transfer())
 v
human answers            (record_human_answered(), from an adapter callback)
 v
private consultation     (already true once the consultation leg exists --
                           the caller has not yet joined it)
 v
bridge caller <-> human  (bridge_transfer())
 v
AI exits                 (a side effect of bridge_transfer()'s own
                           `EVENT_TRANSFER_AI_LEG_REMOVED` milestone --
                           see product/telephony/provider.py's own
                           "Remove AI leg is deliberately not a separate
                           method" reasoning)
```

with every failure branch (`record_transfer_failed()`) converging on the
one approved fallback: the call returns to `STATUS_IN_PROGRESS` (the AI
path), never voicemail, never a second destination attempt, never an
automatic provider switch mid-call.

**Every state change goes through `product/telephony/calls.py`'s own
transfer-safety primitives** (post-implementation HIGH-1 security-audit
remediation):

- `try_start_transfer_attempt()` -- the one atomic claim gate a transfer
  must win *before* `create_consultation_leg()` is ever called. Losing
  the claim (the call is not `in_progress`, or a transfer is already
  active) is a normal outcome, never an exception, and never triggers a
  provider call.
- `try_consume_transfer_attempt_for_bridge()` -- the one atomic
  confirm-and-consume gate a callback must win *before* `bridge_call()`
  is ever called. A stale, duplicate, or superseded callback loses this
  gate and never reaches the provider.
- `apply_call_transfer_event()` -- every other, informational-only
  transfer milestone (consultation-started/human-answered/bridged/
  ai-leg-removed/failed), optionally gated by `expected_attempt_id` so a
  callback belonging to an already-superseded attempt cannot mutate the
  call on behalf of a newer one.

This module owns no database session and no `Call`/`CallEvent` row
directly -- it only ever asks `product/telephony/calls.py` "did I just
win the right to do X," and only calls a real `TelephonyProvider` method
after receiving `True`.

**The destination is never chosen here.** `initiate_transfer()` calls
`product/telephony/destinations.py::resolve_human_destination()` --
the one, sole, trusted source -- and returns `"unavailable"` immediately,
performing no provider operation at all, if the tenant has configured
none. No fallback destination (caller's own number, tenant owner's
profile, a global default) is ever substituted.

**Never a general-purpose call-orchestration engine.** There is no retry
loop, no scheduler, no persisted transfer-attempt table beyond the one
narrow `Call.active_transfer_attempt_id` column -- a transfer's own
bounded timeout is the adapter's own responsibility
(`product/telephony/adapters/twilio_provider.py`'s own module docstring
explains how Twilio's own call-creation `Timeout` parameter is used for
this, rather than a Marketstack-owned timer)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from product.telephony.calls import (
    EVENT_TRANSFER_AI_LEG_REMOVED,
    EVENT_TRANSFER_BRIDGED,
    EVENT_TRANSFER_CONSULTATION_STARTED,
    EVENT_TRANSFER_FAILED,
    EVENT_TRANSFER_HUMAN_ANSWERED,
    apply_call_transfer_event,
    try_consume_transfer_attempt_for_bridge,
    try_start_transfer_attempt,
)
from product.telephony.destinations import resolve_human_destination
from product.telephony.errors import TelephonyProviderError
from product.telephony.provider import ConsultationLeg, TelephonyProvider

#: The closed set of transfer-failure reasons this phase normalizes
#: (docs/ROADMAP.md Phase 27.0's own "normalize at least" list) --
#: recorded only as `core.audit_log` metadata (never a new `CallEvent`
#: column, module docstring's own "no arbitrary payload" discipline), and
#: never surfaced as a distinct domain event type: every one of these
#: converges on the exact same `EVENT_TRANSFER_FAILED` -> bounded
#: return-to-AI outcome.
TransferFailureReason = Literal[
    "busy",
    "no_answer",
    "rejected",
    "failed",
    "canceled",
    "timeout",
    "bridge_failure",
    "provider_unavailable",
]

TransferOutcome = Literal[
    "consultation_started", "unavailable", "already_transferring", "provider_error"
]


@dataclass(frozen=True, slots=True)
class TransferResult:
    outcome: TransferOutcome
    consultation_leg: ConsultationLeg | None = None
    attempt_id: uuid.UUID | None = None


def initiate_transfer(
    *,
    tenant_id: uuid.UUID,
    provider_call_id: str,
    provider: TelephonyProvider,
    request_id: str,
) -> TransferResult:
    """Called per AI `escalate` decision (the closed `CallDecision`
    vocabulary, `product/telephony/call_session.py`) -- never by caller
    input, never with an AI-supplied destination. `provider_call_id`
    (unique per tenant+provider, `Call`'s own partial unique index) is
    what identifies *which* call this transfer belongs to throughout this
    module.

    **HIGH-1 remediation.** A fresh `attempt_id` is generated here (never
    caller-supplied) and must be atomically claimed via
    `try_start_transfer_attempt()` *before* `provider.create_consultation_leg()`
    is ever called. If the claim is lost -- a retried `escalate` for the
    same turn arriving after the first attempt already claimed the call,
    or a genuinely concurrent second transfer attempt -- this function
    returns `"already_transferring"` immediately, performs no provider
    call, and creates no second consultation leg."""
    destination = resolve_human_destination(tenant_id)
    if destination is None:
        return TransferResult(outcome="unavailable")

    attempt_id = uuid.uuid4()
    claimed = try_start_transfer_attempt(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        attempt_id=attempt_id,
        provider_event_id=f"transfer-requested:{provider_call_id}:{request_id}",
    )
    if not claimed:
        return TransferResult(outcome="already_transferring")

    try:
        leg = provider.create_consultation_leg(
            original_provider_call_id=provider_call_id,
            human_destination=destination.value,
            tenant_id=str(tenant_id),
            attempt_id=str(attempt_id),
        )
    except TelephonyProviderError:
        # We hold the claim (this attempt is still active/unconsumed) --
        # `attempt_id` is passed so `record_transfer_failed()` verifies it
        # is still ours before releasing it.
        record_transfer_failed(
            tenant_id=tenant_id,
            provider_call_id=provider_call_id,
            provider=provider,
            request_id=request_id,
            reason="provider_unavailable",
            attempt_id=attempt_id,
        )
        return TransferResult(outcome="provider_error")

    apply_call_transfer_event(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        provider_event_id=f"transfer-consultation:{leg.provider_leg_id}",
        event_type=EVENT_TRANSFER_CONSULTATION_STARTED,
        expected_attempt_id=attempt_id,
    )
    return TransferResult(
        outcome="consultation_started", consultation_leg=leg, attempt_id=attempt_id
    )


def record_human_answered(
    *,
    tenant_id: uuid.UUID,
    provider_call_id: str,
    provider: TelephonyProvider,
    consultation_leg: ConsultationLeg,
    attempt_id: uuid.UUID,
) -> None:
    """Called from the adapter's own consultation-leg status callback
    (`product/telephony/adapters/twilio_webhooks.py`) once the human has
    answered -- an informational milestone; `Call.status` remains
    `transferring`. `attempt_id` (HIGH-1 remediation, sourced from the
    signature-bound callback URL, never caller-supplied) gates this
    against a stale callback belonging to an already-superseded
    attempt."""
    apply_call_transfer_event(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        provider_event_id=f"transfer-answered:{consultation_leg.provider_leg_id}",
        event_type=EVENT_TRANSFER_HUMAN_ANSWERED,
        expected_attempt_id=attempt_id,
    )


def bridge_transfer(
    *,
    tenant_id: uuid.UUID,
    provider_call_id: str,
    provider: TelephonyProvider,
    consultation_leg: ConsultationLeg,
    attempt_id: uuid.UUID,
) -> bool:
    """Connect caller <-> human and end the AI's own handling of the
    original leg. Returns `True` on success (`Call.status` returns to
    `STATUS_IN_PROGRESS`); returns `False` without calling
    `provider.bridge_call()` at all if the atomic consume gate
    (`try_consume_transfer_attempt_for_bridge()`) is lost -- the transfer
    already failed/timed out, this attempt was already bridged by an
    earlier (duplicate) callback, or `attempt_id` belongs to a
    since-superseded attempt (HIGH-1 remediation: the consume happens
    *before* any real provider call, never after).

    On a genuine provider failure (the consume succeeded, but the real
    `bridge_call()` itself errors), records `EVENT_TRANSFER_FAILED`
    (`reason="bridge_failure"`) and returns `False` -- the caller of this
    function performs no further action itself: the approved bounded
    fallback is already satisfied by the `Call.status` transition
    `apply_call_transfer_event()` already applied."""
    claimed = try_consume_transfer_attempt_for_bridge(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        attempt_id=attempt_id,
    )
    if not claimed:
        return False

    try:
        provider.bridge_call(
            original_provider_call_id=provider_call_id, consultation_leg=consultation_leg
        )
    except TelephonyProviderError:
        # The attempt was already consumed by the gate above -- do not
        # re-check `expected_attempt_id` here (it has already been
        # cleared by the successful consume, so a match is no longer
        # possible or meaningful); this call already exclusively owns the
        # right to close out this attempt.
        record_transfer_failed(
            tenant_id=tenant_id,
            provider_call_id=provider_call_id,
            provider=provider,
            request_id=consultation_leg.provider_leg_id,
            reason="bridge_failure",
        )
        return False

    apply_call_transfer_event(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        provider_event_id=f"transfer-bridged:{consultation_leg.provider_leg_id}",
        event_type=EVENT_TRANSFER_BRIDGED,
    )
    apply_call_transfer_event(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        provider_event_id=f"transfer-ai-exit:{consultation_leg.provider_leg_id}",
        event_type=EVENT_TRANSFER_AI_LEG_REMOVED,
    )
    return True


def record_transfer_failed(
    *,
    tenant_id: uuid.UUID,
    provider_call_id: str,
    provider: TelephonyProvider,
    request_id: str,
    reason: TransferFailureReason,
    attempt_id: uuid.UUID | None = None,
) -> None:
    """The one entrypoint for every failure branch this phase normalizes
    (busy/no-answer/rejected/failed/canceled/timeout/bridge-failure/
    provider-unavailable) -- all converge on the identical
    `EVENT_TRANSFER_FAILED` -> bounded-return-to-AI outcome.

    `attempt_id`, when supplied (HIGH-1 remediation), gates this failure
    against a stale/superseded attempt -- pass it for any failure signal
    that arrives while the attempt is still active/unconsumed (a
    consultation-leg-creation error, or a busy/no-answer/failed/canceled
    status callback); omit it (leave `None`) when the attempt has already
    been consumed by `try_consume_transfer_attempt_for_bridge()` (a
    post-consume `bridge_call()` provider failure), since at that point
    `active_transfer_attempt_id` has already been cleared and this call
    already exclusively owns closing out the attempt.

    `reason` is recorded as `core.audit_log` metadata only, for operator
    diagnosis -- never a distinct `CallEvent`/domain-visible outcome; the
    caller (AI/CallSession layer) sees exactly one thing regardless of
    `reason`: the transfer did not succeed, the caller is back with the
    AI."""
    apply_call_transfer_event(
        tenant_id=tenant_id,
        provider_name=provider.name,
        provider_call_id=provider_call_id,
        provider_event_id=f"transfer-failed:{provider_call_id}:{request_id}:{reason}",
        event_type=EVENT_TRANSFER_FAILED,
        audit_metadata={"failure_reason": reason},
        expected_attempt_id=attempt_id,
    )


__all__ = [
    "TransferFailureReason",
    "TransferOutcome",
    "TransferResult",
    "bridge_transfer",
    "initiate_transfer",
    "record_human_answered",
    "record_transfer_failed",
]
