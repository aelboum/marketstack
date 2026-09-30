"""`product/telephony/transfer.py` end-to-end against the real `Call`
state machine and `CallEvent` idempotency ledger (docs/ROADMAP.md Phase
27.0). Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run.

The tests from `test_duplicate_initiate_...` through
`test_stale_attempt_...` are the Phase 27.0 HIGH-1 post-implementation
security-audit remediation's own regression suite -- each one first
documents, then proves closed, one of the exact race/idempotency gaps
the audit identified by code inspection (none of them were caught by the
pre-remediation test suite, which is why the audit found them by reading
the code, not by a failing test).
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.telephony.calls import (
    EVENT_CALL_ANSWERED,
    EVENT_CALL_INITIATED,
    get_call,
    receive_inbound_call_event,
)
from product.telephony.destinations import set_human_transfer_destination
from product.telephony.models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_TRANSFERRING,
)
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import ConsultationLeg, FakeTelephonyProvider
from product.telephony.transfer import (
    bridge_transfer,
    initiate_transfer,
    record_human_answered,
    record_transfer_failed,
)

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"
_PROVIDER_CALL_ID = "provider-call-transfer-1"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _signed(provider: FakeTelephonyProvider, body: bytes) -> dict[str, str]:
    return {_HEADER: provider.compute_signature(body)}


def _bring_call_to_in_progress(
    provider: FakeTelephonyProvider, to_number: str, *, provider_call_id: str = _PROVIDER_CALL_ID
) -> None:
    body = b"payload"
    receive_inbound_call_event(
        provider=provider,
        headers=_signed(provider, body),
        body=body,
        provider_event_id=f"evt-initiated-{provider_call_id}",
        event_type=EVENT_CALL_INITIATED,
        to_number=to_number,
        from_number="+15551234567",
        provider_call_id=provider_call_id,
    )
    receive_inbound_call_event(
        provider=provider,
        headers=_signed(provider, body),
        body=body,
        provider_event_id=f"evt-answered-{provider_call_id}",
        event_type=EVENT_CALL_ANSWERED,
        to_number=to_number,
        from_number="+15551234567",
        provider_call_id=provider_call_id,
    )


def _find_call_id(actor_user_id, tenant_id):
    from product.telephony.calls import list_calls

    calls = list_calls(actor_user_id, tenant_id)
    assert len(calls) == 1
    return calls[0].id


def test_missing_destination_returns_unavailable_and_does_not_touch_call_status() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        assert result.outcome == "unavailable"
        assert result.consultation_leg is None

        call = get_call(owner.id, client.tenant_id, _find_call_id(owner.id, client.tenant_id))
        assert call.status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_full_successful_transfer_sequence() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        assert result.outcome == "consultation_started"
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        call_id = _find_call_id(owner.id, client.tenant_id)
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING

        record_human_answered(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING

        bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert bridged is True
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
        assert len(provider._bridged) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_transfer_failure_returns_call_to_in_progress() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        record_transfer_failed(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id=result.consultation_leg.provider_leg_id,
            reason="no_answer",
            attempt_id=result.attempt_id,
        )
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_bridge_provider_failure_is_normalized_and_returns_to_ai() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        provider.fail = True
        bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert bridged is False
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_provider_call_id_is_a_safe_no_op() -> None:
    from product.telephony.calls import EVENT_TRANSFER_FAILED, apply_call_transfer_event

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        result = apply_call_transfer_event(
            tenant_id=client.tenant_id,
            provider_name=provider.name,
            provider_call_id="no-such-call",
            provider_event_id="evt-x",
            event_type=EVENT_TRANSFER_FAILED,
        )
        assert result is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- HIGH-1 remediation regression suite (Part A.8) -----------------------


def test_duplicate_initiate_creates_exactly_one_consultation_leg() -> None:
    """Part A.8 Test 1 -- retrying `initiate_transfer()` for the same
    logical request (the call is already `transferring`, whether from the
    identical `request_id` or a different one) must not create a second
    consultation leg."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        first = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        assert first.outcome == "consultation_started"

        # Retried with the IDENTICAL request_id (e.g. a retried escalate
        # decision for the same turn).
        retried = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        assert retried.outcome == "already_transferring"
        assert retried.consultation_leg is None
        assert len(provider._consultation_legs) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_initiate_creates_exactly_one_consultation_leg() -> None:
    """Part A.8 Test 2 -- a genuinely concurrent second transfer attempt
    (a DIFFERENT request_id, e.g. two distinct turns both deciding to
    escalate) must also lose the claim and create no second leg."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        attempt_a = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-A",
        )
        attempt_b = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-B",
        )
        assert attempt_a.outcome == "consultation_started"
        assert attempt_b.outcome == "already_transferring"
        assert attempt_b.consultation_leg is None
        assert len(provider._consultation_legs) == 1

        call_id = _find_call_id(owner.id, client.tenant_id)
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_late_human_answer_after_recorded_failure_does_not_bridge() -> None:
    """Part A.8 Test 3 -- once EVENT_TRANSFER_FAILED has been recorded
    (the attempt's own active_transfer_attempt_id is cleared and
    Call.status is back to in_progress), a late human-answer/in-progress
    callback for that SAME (now-closed) attempt must not call
    bridge_call()."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        record_transfer_failed(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id=result.consultation_leg.provider_leg_id,
            reason="no_answer",
            attempt_id=result.attempt_id,
        )
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS

        # The late "human actually answered" callback, for the SAME
        # already-failed attempt/leg, arrives after the fact.
        record_human_answered(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert bridged is False
        assert len(provider._bridged) == 0
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_answer_callback_bridges_at_most_once() -> None:
    """Part A.8 Test 4 -- the identical "human answered" callback
    delivered twice (Twilio's own documented at-least-once delivery) must
    call bridge_call() at most once."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        first_bridge = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        second_bridge = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert first_bridge is True
        assert second_bridge is False
        assert len(provider._bridged) == 1
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_terminal_call_callback_has_no_provider_side_effect_and_does_not_raise() -> None:
    """Part A.8 Test 5 -- a transfer callback for a call that has
    independently reached a terminal status (caller hung up) must not
    raise, must not resurrect the call, and must not call the provider."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        # The caller hangs up while the transfer is still in flight --
        # the ordinary inbound-call pipeline moves the call straight to
        # `completed` from `transferring`.
        from product.telephony.calls import EVENT_CALL_COMPLETED

        completed_body = b"caller-hangup"
        receive_inbound_call_event(
            provider=provider,
            headers=_signed(provider, completed_body),
            body=completed_body,
            provider_event_id="evt-caller-hangup",
            event_type=EVENT_CALL_COMPLETED,
            to_number=number.phone_number,
            from_number="+15551234567",
            provider_call_id=_PROVIDER_CALL_ID,
        )
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_COMPLETED

        # A transfer callback for this now-terminal call must not raise,
        # must not resurrect it, and must not bridge.
        bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=result.consultation_leg,
            attempt_id=result.attempt_id,
        )
        assert bridged is False
        assert len(provider._bridged) == 0
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_COMPLETED

        record_transfer_failed(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id=result.consultation_leg.provider_leg_id,
            reason="no_answer",
            attempt_id=result.attempt_id,
        )
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_COMPLETED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_stale_attempt_callback_cannot_bridge_a_newer_attempt() -> None:
    """Part A.8 Test 6 -- a callback carrying an OLDER, already-superseded
    attempt id must not be able to bridge (or otherwise affect) a NEWER
    attempt that has since started on the same call."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _bring_call_to_in_progress(provider, number.phone_number)
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        old_attempt = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-1",
        )
        assert old_attempt.consultation_leg is not None
        assert old_attempt.attempt_id is not None
        old_leg = old_attempt.consultation_leg
        old_attempt_id = old_attempt.attempt_id

        # The old attempt fails/times out -- the call returns to
        # in_progress, releasing the claim.
        record_transfer_failed(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id=old_leg.provider_leg_id,
            reason="no_answer",
            attempt_id=old_attempt_id,
        )

        # A NEW transfer attempt starts on the same call.
        new_attempt = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            request_id="turn-2",
        )
        assert new_attempt.outcome == "consultation_started"
        assert new_attempt.attempt_id is not None
        assert new_attempt.attempt_id != old_attempt_id
        call_id = _find_call_id(owner.id, client.tenant_id)
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING

        # A LATE callback belonging to the OLD attempt/leg now arrives.
        # It must not be able to bridge the NEW attempt.
        stale_bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=old_leg,
            attempt_id=old_attempt_id,
        )
        assert stale_bridged is False
        assert len(provider._bridged) == 0
        # The NEW attempt's own state must be completely unaffected.
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING

        # The NEW attempt can still legitimately bridge afterward.
        new_bridged = bridge_transfer(
            tenant_id=client.tenant_id,
            provider_call_id=_PROVIDER_CALL_ID,
            provider=provider,
            consultation_leg=ConsultationLeg(provider_leg_id="fake-leg-new"),
            attempt_id=new_attempt.attempt_id,
        )
        assert new_bridged is True
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
