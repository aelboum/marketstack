"""`product/ai/tools/*.py` invoked through `invoke_product_ai_tool()`
against real, disposable Postgres -- authorization (RBAC + Data
Authorization), tenant isolation, bounded input, and audit behavior
(docs/ROADMAP.md Phase 9.1/9.3). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import pytest
from control_plane.data_authorization import TenantAIDataPolicy
from control_plane.orchestration import ToolRegistry
from control_plane.orchestration.errors import (
    DataAuthorizationRequiredError,
    ToolExecutionError,
    UnauthorizedToolInvocationError,
)
from core.audit_log import list as list_audit_log
from product.agency.provisioning import provision_agency, provision_client
from product.ai.invocation import invoke_product_ai_tool
from product.ai.provider import MAX_USER_CONTENT_CHARS, FakeLLMProvider, LLMCompletion
from product.ai.tools.conversation_summarization import build_conversation_summarization_tool
from product.ai.tools.lead_qualification import build_lead_qualification_tool
from product.ai.tools.suggested_next_actions import build_suggested_next_actions_tool
from product.ai.tools.suggested_reply import build_suggested_reply_tool
from product.conversations.messages import create_message, list_messages
from product.conversations.models import DIRECTION_INBOUND
from product.conversations.threads import create_thread
from product.crm.contacts import create_contact
from product.crm.opportunities import create_opportunity
from product.crm.pipelines import create_pipeline, create_stage

from tests.ai._cleanup import cleanup_tenant_tree, cleanup_users, make_user


@dataclass
class _StructuredFakeLLMProvider:
    """A `LLMProvider` test double shaped for `ai.crm.qualify_lead`'s own
    Phase 26A structured JSON contract -- the shared `FakeLLMProvider`
    (`product/ai/provider.py`) returns a fixed non-JSON marker by design
    (deliberately, visibly synthetic, and used unmodified by every other
    tool in this suite), so it cannot exercise a real structured-decision
    parse. This double stays local to this test file rather than changing
    the shared `FakeLLMProvider` shape every other AI tool test relies on.
    """

    decision: str = "qualified"
    reason: str = "Contact has a name, email, and phone on file."
    qualification: str = "Looks like a promising lead."
    requests: list[tuple[str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        self.requests.append((system_prompt, user_content))
        payload = json.dumps(
            {"decision": self.decision, "reason": self.reason, "qualification": self.qualification}
        )
        return LLMCompletion(text=payload[:max_output_chars], provider_name=self.name)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _permissive_policy(tenant_id: uuid.UUID, purpose: str) -> TenantAIDataPolicy:
    return TenantAIDataPolicy(
        tenant_id=tenant_id,
        allowed_data_classifications=frozenset({"tenant_data"}),
        allowed_purposes=frozenset({purpose}),
        allowed_providers=frozenset({"fake"}),
    )


# --- ai.crm.qualify_lead ------------------------------------------------


async def test_qualify_lead_authorized_invocation_succeeds() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = _StructuredFakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        outcome = await invoke_product_ai_tool(
            "ai.crm.qualify_lead",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.qualify_lead"),
            registry=registry,
        )
        assert outcome.output["contact_id"] == str(contact.id)
        assert outcome.output["provider"] == "fake"
        assert outcome.output["decision"] == "qualified"
        assert outcome.output["reason"] == provider.reason
        assert outcome.output["qualification"] == provider.qualification
        assert provider.requests  # the fake provider was actually called
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


@pytest.mark.parametrize("decision", ["qualified", "not_qualified", "needs_more_info"])
async def test_qualify_lead_returns_each_allowed_decision(decision: str) -> None:
    """Phase 26A's closed decision vocabulary -- one case per allowed
    value, each carrying its own `reason`/`qualification` through
    unchanged alongside the always-present `contact_id`/`provider`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = _StructuredFakeLLMProvider(
        decision=decision, reason=f"reason for {decision}", qualification=f"note for {decision}"
    )
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        outcome = await invoke_product_ai_tool(
            "ai.crm.qualify_lead",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.qualify_lead"),
            registry=registry,
        )
        assert outcome.output["contact_id"] == str(contact.id)
        assert outcome.output["provider"] == "fake"
        assert outcome.output["decision"] == decision
        assert outcome.output["reason"] == f"reason for {decision}"
        assert outcome.output["qualification"] == f"note for {decision}"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


@pytest.mark.parametrize(
    "raw_completion",
    [
        json.dumps({"decision": "maybe", "reason": "x", "qualification": "y"}),
        json.dumps({"decision": "", "reason": "x", "qualification": "y"}),
        json.dumps({"decision": None, "reason": "x", "qualification": "y"}),
        json.dumps({"reason": "x", "qualification": "y"}),  # decision missing
        json.dumps({"decision": "qualified", "qualification": "y"}),  # reason missing
        json.dumps({"decision": "qualified", "reason": "x"}),  # qualification missing
        json.dumps({"decision": 123, "reason": "x", "qualification": "y"}),  # wrong type
        json.dumps({"decision": "qualified", "reason": [], "qualification": "y"}),  # wrong type
        json.dumps({"decision": "qualified", "reason": "x", "qualification": {}}),  # wrong type
        # oversized reason
        json.dumps({"decision": "qualified", "reason": "x" * 241, "qualification": "y"}),
        # oversized qualification
        json.dumps({"decision": "qualified", "reason": "x", "qualification": "y" * 2001}),
        "not json at all",
        "[]",
    ],
)
async def test_qualify_lead_rejects_malformed_structured_completion(raw_completion: str) -> None:
    """Every deterministically-invalid model completion this phase's own
    contract names -- invalid/missing/wrong-typed/oversized -- fails
    explicitly as a `ToolExecutionError` (the Control Plane's own generic
    handler-failure wrapping of the `AIProviderError` the tool itself
    raises), never a silently-invented decision and never a truncation."""

    class _RawCompletionProvider:
        name = "fake"

        def complete(self, *, system_prompt, user_content, max_output_chars):
            return LLMCompletion(text=raw_completion, provider_name=self.name)

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(_RawCompletionProvider()))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        with pytest.raises(ToolExecutionError):
            await invoke_product_ai_tool(
                "ai.crm.qualify_lead",
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.qualify_lead"),
                registry=registry,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_qualify_lead_unauthorized_actor_denied_and_provider_never_called() -> None:
    """AI action cannot bypass authorization -- an actor with no
    membership in the tenant is denied by RBAC before the handler (and
    therefore the LLM provider) ever runs."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        with pytest.raises(UnauthorizedToolInvocationError):
            await invoke_product_ai_tool(
                "ai.crm.qualify_lead",
                actor_user_id=unrelated.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.qualify_lead"),
                registry=registry,
            )
        assert provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


async def test_qualify_lead_denied_without_a_tenant_ai_policy() -> None:
    """No persisted tenant AI policy exists yet (product/ai/policy.py's
    own module docstring) -- omitting `tenant_policy` must deny via Data
    Authorization, never silently allow."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        with pytest.raises(DataAuthorizationRequiredError):
            await invoke_product_ai_tool(
                "ai.crm.qualify_lead",
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                registry=registry,
            )
        assert provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_qualify_lead_cross_tenant_contact_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        with pytest.raises(ToolExecutionError):
            await invoke_product_ai_tool(
                "ai.crm.qualify_lead",
                actor_user_id=other_owner.id,
                tenant_id=other_client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                tenant_policy=_permissive_policy(other_client.tenant_id, "ai.crm.qualify_lead"),
                registry=registry,
            )
        assert provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


async def test_qualify_lead_invocation_is_audited_allow_and_deny() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = _StructuredFakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(provider))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        await invoke_product_ai_tool(
            "ai.crm.qualify_lead",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.qualify_lead"),
            registry=registry,
        )
        with pytest.raises(DataAuthorizationRequiredError):
            await invoke_product_ai_tool(
                "ai.crm.qualify_lead",
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                registry=registry,
            )

        tool_entries = list_audit_log(
            client.tenant_id, resource_type="control_plane_tool", resource_id="ai.crm.qualify_lead"
        )
        assert any(e.outcome == "success" for e in tool_entries)
        assert any(e.outcome == "denied" for e in tool_entries)

        data_auth_entries = list_audit_log(client.tenant_id, resource_type="ai_data_authorization")
        assert any(e.action == "ai_control_plane.data_access_approved" for e in data_auth_entries)
        assert any(e.action == "ai_control_plane.data_access_denied" for e in data_auth_entries)
        # Never the contact's own name/email/phone in any audit entry.
        for entry in tool_entries + data_auth_entries:
            assert "Ada" not in str(entry.metadata)
            assert "Lovelace" not in str(entry.metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- ai.crm.suggest_next_actions ----------------------------------------


async def test_suggest_next_actions_authorized_invocation_succeeds() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_suggested_next_actions_tool(provider))
    try:
        pipeline = create_pipeline(owner.id, client.tenant_id, name="Sales")
        stage = create_stage(owner.id, client.tenant_id, pipeline.id, name="Lead", position=0)
        opportunity = create_opportunity(
            owner.id,
            client.tenant_id,
            name="Big Deal",
            pipeline_id=pipeline.id,
            stage_id=stage.id,
        )
        outcome = await invoke_product_ai_tool(
            "ai.crm.suggest_next_actions",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.opportunity",
            resource_id=str(opportunity.id),
            payload={"opportunity_id": str(opportunity.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.crm.suggest_next_actions"),
            registry=registry,
        )
        assert outcome.output["opportunity_id"] == str(opportunity.id)
        assert provider.requests
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- ai.conversations.summarize / ai.conversations.suggest_reply --------


def _thread_with_messages(owner_id, tenant_id):
    contact = create_contact(owner_id, tenant_id, first_name="P", last_name="Erson")
    thread = create_thread(owner_id, tenant_id, contact_id=contact.id, channel="email")
    create_message(
        owner_id,
        tenant_id,
        thread.id,
        direction=DIRECTION_INBOUND,
        is_internal_note=False,
        body="Hello, I have a question.",
        author_user_id=None,
    )
    return thread


async def test_summarize_conversation_authorized_invocation_succeeds() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_conversation_summarization_tool(provider))
    try:
        thread = _thread_with_messages(owner.id, client.tenant_id)
        outcome = await invoke_product_ai_tool(
            "ai.conversations.summarize",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="conversations.thread",
            resource_id=str(thread.id),
            payload={"thread_id": str(thread.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.conversations.summarize"),
            registry=registry,
        )
        assert outcome.output["message_count"] == 1
        assert provider.requests
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_suggest_reply_never_sends_and_marks_sent_false() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_suggested_reply_tool(provider))
    try:
        thread = _thread_with_messages(owner.id, client.tenant_id)
        outcome = await invoke_product_ai_tool(
            "ai.conversations.suggest_reply",
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="conversations.thread",
            resource_id=str(thread.id),
            payload={"thread_id": str(thread.id)},
            tenant_policy=_permissive_policy(client.tenant_id, "ai.conversations.suggest_reply"),
            registry=registry,
        )
        assert outcome.output["sent"] is False
        assert outcome.output["draft_reply"]

        messages = list_messages(owner.id, client.tenant_id, thread.id)
        # Only the one message this test itself created via create_message()
        # -- the suggest-reply tool must never have added a second one.
        assert len(messages) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_summarize_conversation_rejects_malformed_thread_id() -> None:
    """Bounded/validated input: a malformed `thread_id` is rejected before
    ever reaching the provider (the handler's own `require_uuid()`
    boundary, separate from `LLMProvider.complete()`'s own content
    bound)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.register(build_suggested_reply_tool(provider))
    try:
        thread = _thread_with_messages(owner.id, client.tenant_id)
        with pytest.raises(ToolExecutionError):
            await invoke_product_ai_tool(
                "ai.conversations.suggest_reply",
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="conversations.thread",
                resource_id=str(thread.id),
                payload={"thread_id": "x" * (MAX_USER_CONTENT_CHARS + 1)},
                tenant_policy=_permissive_policy(
                    client.tenant_id, "ai.conversations.suggest_reply"
                ),
                registry=registry,
            )
        assert provider.requests == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
