"""`ai.telephony.receptionist_advice` tool against real, disposable
Postgres -- consumes an existing Phase 8 `Call` read-only, never mutates
telephony state, advisory `handle`/`escalate` decision surfaces the
already-routed human (docs/ROADMAP.md Phase 9.2). Marked `integration`,
excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from control_plane.data_authorization import TenantAIDataPolicy
from control_plane.orchestration import ToolRegistry
from control_plane.orchestration.errors import ToolExecutionError
from product.agency.provisioning import provision_agency, provision_client
from product.ai.invocation import invoke_product_ai_tool
from product.ai.provider import FakeLLMProvider
from product.ai.receptionist import ESCALATION_CONFIDENCE_THRESHOLD, build_receptionist_advice_tool
from product.telephony.calls import (
    EVENT_CALL_INITIATED,
    EVENT_CALL_NO_ANSWER,
    get_call,
    receive_inbound_call_event,
)
from product.telephony.numbers import add_routing_target, provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.ai._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

_HEADER = "X-Fake-Telephony-Signature"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _permissive_policy(tenant_id: uuid.UUID) -> TenantAIDataPolicy:
    return TenantAIDataPolicy(
        tenant_id=tenant_id,
        allowed_data_classifications=frozenset({"tenant_data"}),
        allowed_purposes=frozenset({"ai.telephony.receptionist_advice"}),
        allowed_providers=frozenset({"fake"}),
    )


def _create_ringing_call(owner_id, tenant_id, telephony_provider):
    """Returns `(call, to_number)` -- the caller keeps `to_number` around
    to replay a second provider event against the same call without a
    second, untenanted `PhoneNumber` lookup of its own."""
    number = provision_phone_number(
        owner_id, tenant_id, country_code="US", provider=telephony_provider
    )
    add_routing_target(owner_id, tenant_id, number.id, user_id=owner_id)
    body = b"payload"
    call = receive_inbound_call_event(
        provider=telephony_provider,
        headers={_HEADER: telephony_provider.compute_signature(body)},
        body=body,
        provider_event_id="evt-1",
        event_type=EVENT_CALL_INITIATED,
        to_number=number.phone_number,
        from_number="+15551234567",
        provider_call_id="pc-1",
    )
    assert call is not None
    return call, number.phone_number


async def test_high_confidence_handles_and_drafts_a_response() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    llm_provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_receptionist_advice_tool(llm_provider))
    try:
        call, _to_number = _create_ringing_call(owner.id, client.tenant_id, telephony_provider)
        outcome = await invoke_product_ai_tool(
            "ai.telephony.receptionist_advice",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="telephony.call",
            resource_id=str(call.id),
            payload={
                "call_id": str(call.id),
                "transcript": "I'd like to book an appointment.",
                "confidence": ESCALATION_CONFIDENCE_THRESHOLD,
            },
            tenant_policy=_permissive_policy(client.tenant_id),
            registry=registry,
        )
        assert outcome.output["action"] == "handle"
        assert outcome.output["draft_response"]
        assert llm_provider.requests
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_low_confidence_escalates_without_calling_the_llm() -> None:
    """Below the defined confidence/scope boundary, the tool escalates --
    the LLM provider is never even called for a call it declines to
    handle, and the already-routed human's own `assigned_user_id`
    surfaces in the output (this module never reassigns/re-routes)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    llm_provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_receptionist_advice_tool(llm_provider))
    try:
        call, _to_number = _create_ringing_call(owner.id, client.tenant_id, telephony_provider)
        outcome = await invoke_product_ai_tool(
            "ai.telephony.receptionist_advice",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="telephony.call",
            resource_id=str(call.id),
            payload={
                "call_id": str(call.id),
                "transcript": "I'd like to book an appointment.",
                "confidence": ESCALATION_CONFIDENCE_THRESHOLD - 0.01,
            },
            tenant_policy=_permissive_policy(client.tenant_id),
            registry=registry,
        )
        assert outcome.output["action"] == "escalate"
        assert outcome.output["draft_response"] is None
        assert outcome.output["assigned_user_id"] == str(owner.id)
        assert llm_provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_receptionist_advice_never_mutates_the_call() -> None:
    """The tool is read-only -- the call's own status is unchanged by
    either a handle or an escalate decision (`get_call()` reads it again
    after the invocation and finds it unchanged)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    llm_provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_receptionist_advice_tool(llm_provider))
    try:
        call, _to_number = _create_ringing_call(owner.id, client.tenant_id, telephony_provider)
        await invoke_product_ai_tool(
            "ai.telephony.receptionist_advice",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="telephony.call",
            resource_id=str(call.id),
            payload={"call_id": str(call.id), "transcript": "Hello?", "confidence": 1.0},
            tenant_policy=_permissive_policy(client.tenant_id),
            registry=registry,
        )
        after = get_call(owner.id, client.tenant_id, call.id)
        assert after.status == "ringing"
        assert after.assigned_user_id == owner.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_receptionist_advice_for_completed_call_rejected() -> None:
    """A terminal call cannot be advised on -- the AI must not attempt to
    handle a call that has already ended."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    llm_provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_receptionist_advice_tool(llm_provider))
    try:
        call, to_number = _create_ringing_call(owner.id, client.tenant_id, telephony_provider)
        body = b"payload2"
        receive_inbound_call_event(
            provider=telephony_provider,
            headers={_HEADER: telephony_provider.compute_signature(body)},
            body=body,
            provider_event_id="evt-2",
            event_type=EVENT_CALL_NO_ANSWER,
            to_number=to_number,
            from_number="+15551234567",
            provider_call_id="pc-1",
        )
        with pytest.raises(ToolExecutionError):
            await invoke_product_ai_tool(
                "ai.telephony.receptionist_advice",
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="telephony.call",
                resource_id=str(call.id),
                payload={"call_id": str(call.id), "transcript": "Hello?", "confidence": 1.0},
                tenant_policy=_permissive_policy(client.tenant_id),
                registry=registry,
            )
        assert llm_provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
