"""Inbound provider-event processing: signature verification, tenant
resolution, idempotency/replay protection, routing, the call state
machine, and concurrency (docs/ROADMAP.md Phase 8.2). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.telephony.calls import (
    EVENT_CALL_ANSWERED,
    EVENT_CALL_COMPLETED,
    EVENT_CALL_INITIATED,
    EVENT_CALL_NO_ANSWER,
    get_call,
    list_calls,
    receive_inbound_call_event,
)
from product.telephony.errors import (
    TelephonyInvalidStateTransitionError,
    TelephonyUnknownNumberError,
    TelephonyWebhookSignatureInvalidError,
)
from product.telephony.numbers import add_routing_target, provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _signed(provider: FakeTelephonyProvider, body: bytes) -> dict[str, str]:
    return {_HEADER: provider.compute_signature(body)}


def _deliver(
    provider: FakeTelephonyProvider,
    *,
    event_id: str,
    event_type: str,
    to_number: str,
    from_number: str = "+15551234567",
    provider_call_id: str = "provider-call-1",
    body: bytes = b"payload",
    now: datetime | None = None,
):
    return receive_inbound_call_event(
        provider=provider,
        headers=_signed(provider, body),
        body=body,
        provider_event_id=event_id,
        event_type=event_type,
        to_number=to_number,
        from_number=from_number,
        provider_call_id=provider_call_id,
        now=now,
    )


def test_forged_signature_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        body = b"payload"
        with pytest.raises(TelephonyWebhookSignatureInvalidError):
            receive_inbound_call_event(
                provider=provider,
                headers={_HEADER: "0" * 64},
                body=body,
                provider_event_id="evt-1",
                event_type=EVENT_CALL_INITIATED,
                to_number=number.phone_number,
                from_number="+15551234567",
                provider_call_id="pc-1",
            )
        assert list_calls(owner.id, client.tenant_id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_number_is_rejected() -> None:
    provider = FakeTelephonyProvider(webhook_secret="s")
    with pytest.raises(TelephonyUnknownNumberError):
        _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number="+19995550000",
            provider_call_id="pc-1",
        )


def test_call_initiated_creates_call_and_routes_it() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        add_routing_target(owner.id, client.tenant_id, number.id, user_id=owner.id)

        view = _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert view is not None
        assert view.status == "ringing"
        assert view.direction == "inbound"
        assert view.assigned_user_id == owner.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_call_initiated_with_no_routing_targets_is_unrouted_not_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        view = _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert view is not None
        assert view.assigned_user_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_call_initiated_event_is_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        first = _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        second = _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert first is not None and second is not None
        assert first.id == second.id
        assert len(list_calls(owner.id, client.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_full_valid_transition_chain_ringing_to_in_progress_to_completed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _deliver(
            provider,
            event_id="evt-init",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        answered = _deliver(
            provider,
            event_id="evt-answer",
            event_type=EVENT_CALL_ANSWERED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert answered is not None
        assert answered.status == "in_progress"
        assert answered.started_at is not None

        completed = _deliver(
            provider,
            event_id="evt-complete",
            event_type=EVENT_CALL_COMPLETED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )
        assert completed is not None
        assert completed.status == "completed"
        assert completed.ended_at is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_terminal_state_rejects_further_transition() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _deliver(
            provider,
            event_id="evt-init",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        _deliver(
            provider,
            event_id="evt-no-answer",
            event_type=EVENT_CALL_NO_ANSWER,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        # An out-of-order "answered" arriving after the call already
        # reached a terminal state -- genuinely invalid, must raise.
        with pytest.raises(TelephonyInvalidStateTransitionError):
            _deliver(
                provider,
                event_id="evt-late-answer",
                event_type=EVENT_CALL_ANSWERED,
                to_number=number.phone_number,
                provider_call_id="pc-1",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_terminal_event_is_idempotent_not_an_error() -> None:
    """The identical event delivered twice (same target status) is a
    no-op, never TelephonyInvalidStateTransitionError -- distinct from a
    genuinely out-of-order event (see the terminal-state test above)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _deliver(
            provider,
            event_id="evt-init",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        _deliver(
            provider,
            event_id="evt-no-answer-1",
            event_type=EVENT_CALL_NO_ANSWER,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        # A *different* provider_event_id for the identical status --
        # exercises the state-machine's own same-status idempotent no-op
        # path (not just CallEvent-level dedup on the same event id).
        second = _deliver(
            provider,
            event_id="evt-no-answer-2",
            event_type=EVENT_CALL_NO_ANSWER,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert second is not None
        assert second.status == "no_answer"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_event_type_for_existing_call_is_a_no_op() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        _deliver(
            provider,
            event_id="evt-init",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        result = _deliver(
            provider,
            event_id="evt-mystery",
            event_type="call.some_unmodeled_event",
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert result is not None
        assert result.status == "ringing"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_status_event_for_unknown_call_returns_none_not_an_error() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        result = _deliver(
            provider,
            event_id="evt-answer-orphan",
            event_type=EVENT_CALL_ANSWERED,
            to_number=number.phone_number,
            provider_call_id="pc-never-initiated",
        )
        assert result is None
        assert list_calls(owner.id, client.tenant_id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_round_robin_routes_to_least_recently_assigned_target() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    agent_a = make_user()
    agent_b = make_user()
    _add_member(owner.id, client.tenant_id, agent_a.id)
    _add_member(owner.id, client.tenant_id, agent_b.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        add_routing_target(owner.id, client.tenant_id, number.id, user_id=agent_a.id)
        add_routing_target(owner.id, client.tenant_id, number.id, user_id=agent_b.id)

        first = _deliver(
            provider,
            event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        second = _deliver(
            provider,
            event_id="evt-2",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-2",
        )
        third = _deliver(
            provider,
            event_id="evt-3",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-3",
        )
        # Never-assigned agents come first (tie-broken by position), then
        # whichever has gone longest without a call.
        assert first is not None and second is not None and third is not None
        assert first.assigned_user_id == agent_a.id
        assert second.assigned_user_id == agent_b.id
        assert third.assigned_user_id == agent_a.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, agent_a.id, agent_b.id)


def test_concurrent_duplicate_call_initiated_delivery_creates_exactly_one_call() -> None:
    """Two threads deliver the identical call.initiated event
    concurrently -- the partial unique index on `telephony.calls` (and
    the CallEvent dedup) must ensure exactly one Call row exists,
    reproduced against real Postgres, not assumed."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )

        results: list[object] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _worker(event_id: str) -> None:
            try:
                barrier.wait(timeout=5)
                view = _deliver(
                    provider,
                    event_id=event_id,
                    event_type=EVENT_CALL_INITIATED,
                    to_number=number.phone_number,
                    provider_call_id="pc-concurrent",
                )
                results.append(view)
            except Exception as exc:  # pragma: no cover -- surfaced via errors list
                errors.append(exc)

        threads = [
            threading.Thread(target=_worker, args=(f"evt-concurrent-{i}",)) for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        assert len(results) == 2
        call_ids = {r.id for r in results}  # type: ignore[attr-defined]
        assert len(call_ids) == 1
        assert len(list_calls(owner.id, client.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_call_after_inbound_flow_reflects_current_state() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        created = _deliver(
            provider,
            event_id="evt-init",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            provider_call_id="pc-1",
        )
        assert created is not None
        fetched = get_call(owner.id, client.tenant_id, created.id)
        assert fetched.status == "ringing"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
