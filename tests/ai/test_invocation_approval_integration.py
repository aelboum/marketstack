"""`product/ai/invocation.py`'s tier>=1 approval integration
(docs/ROADMAP.md Phase 26B) against the real, installed
`control_plane.approvals` -- `propose_action()`/`approve()`/`reject()`/
`execute_approved()`, completely unmodified. Real disposable Postgres.
Marked `integration`, excluded from the default `pytest` run.

**No new production capability.** All five real `product/ai/tools/*.py`
capabilities are documented, deliberately, as `autonomy_tier=0`
read-only/advisory tools (`qualify_lead`/`suggest_next_actions` mirror
each other's "tier 0, read-only" rationale verbatim;
`summarize`/`suggest_reply` are explicitly draft-only, "a human always
sends" -- promoting either to tier>=1 would make the harmless, read-only
act of *drafting* require approval, contradicting the exact reasoning
that makes each tier 0 today). None can be promoted without changing its
documented semantics, so -- exactly as `tests/approvals
/test_approval_inbox_integration.py::_build_test_tool()` already does for
Phase 29 -- these tests build their own minimal, test-scoped tier>=1
`ToolDefinition`, never touching `product/ai/tools/`, `PRODUCTION_CAPABILITIES`,
or any real capability's own `autonomy_tier`. `qualify_lead` itself is
covered below only to prove it is entirely unaffected.
"""

from __future__ import annotations

import uuid

import pytest
from control_plane.approvals import (
    ApprovalNotPendingError,
    ApprovalRequestNotFoundError,
    approve,
    get_approval,
    list_approvals,
)
from control_plane.approvals import reject as reject_approval
from control_plane.data_authorization import TenantAIDataPolicy
from control_plane.orchestration import (
    DataAuthorizationRequiredError,
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    UnauthorizedToolInvocationError,
)
from infra.db import tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.ai.invocation import execute_approved_ai_tool, invoke_product_ai_tool
from product.ai.provider import LLMCompletion
from product.ai.tools.lead_qualification import build_lead_qualification_tool
from product.crm.contacts import create_contact
from product.crm.permissions import CONTACT_RESOURCE
from sqlalchemy import text

from tests.ai._cleanup import cleanup_tenant_tree as _cleanup_ai_tenant_tree
from tests.ai._cleanup import cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TIER1_TOOL_KEY = "test.ai.phase26b_tier1_stub"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`tests/ai/_cleanup.py`'s own tree plus `control_plane
    .approval_requests` (mirrors `tests/approvals/_cleanup.py`'s own
    identical addition for the exact same reason: a proposal FKs to a
    real tenant/user, so it must be deleted before either can be)."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM control_plane.approval_requests WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_ai_tenant_tree(*tenant_ids_leaf_to_root)


def _permissive_policy(tenant_id: uuid.UUID, purpose: str) -> TenantAIDataPolicy:
    return TenantAIDataPolicy(
        tenant_id=tenant_id,
        allowed_data_classifications=frozenset({"tenant_data"}),
        allowed_purposes=frozenset({purpose}),
        allowed_providers=frozenset({"fake"}),
    )


def _build_tier1_tool(
    *, calls: list[dict[str, object]], requires_data_authorization: bool = False
) -> ToolDefinition:
    """A minimal, self-contained, test-scoped tier>=1 tool -- see module
    docstring for why no real `product/ai/tools/*.py` capability is used
    here instead. Reuses `crm.contact`/`read` for
    `required_resource`/`required_action` so the same agency-owner RBAC
    standing every `qualify_lead` test already relies on
    (`tests/ai/test_tools_integration.py`) applies here too, with no
    extra grant setup needed."""

    async def _handler(context, payload):
        calls.append(dict(payload))
        if payload.get("force_fail"):
            raise RuntimeError("forced failure -- Phase 26B failure-behavior test")
        return {"echoed_contact_id": payload.get("contact_id"), "note": "tier1-executed"}

    return ToolDefinition(
        key=TIER1_TOOL_KEY,
        description="Phase 26B test-only tier>=1 stub -- never a real product capability.",
        handler=_handler,
        required_scope_type="tenant",
        required_resource=CONTACT_RESOURCE,
        required_action="read",
        autonomy_tier=1,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=requires_data_authorization,
    )


# --- tier 0: qualify_lead is entirely unaffected ----------------------------


class _StructuredFakeLLMProvider:
    """`ai.crm.qualify_lead` requires a structured JSON completion since
    Phase 26A -- `FakeLLMProvider`'s own fixed, non-JSON marker text
    cannot satisfy it, so this test-local double (mirrors
    `tests/ai/test_tools_integration.py::_StructuredFakeLLMProvider`
    exactly, not imported since that one is file-local) returns a
    minimal valid completion instead."""

    name = "fake"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        self.requests.append((system_prompt, user_content))
        payload = '{"decision": "qualified", "reason": "ok", "qualification": "note"}'
        return LLMCompletion(text=payload[:max_output_chars], provider_name=self.name)


async def test_qualify_lead_tier0_executes_directly_and_creates_no_approval() -> None:
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
        # Real execution happened -- the provider was actually called and
        # a real decision came back -- never a "pending_approval" proposal.
        assert outcome.output["contact_id"] == str(contact.id)
        assert outcome.output["decision"] == "qualified"
        assert provider.requests
        assert list_approvals(client.tenant_id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- tier >= 1: proposal -----------------------------------------------------


async def test_tier1_tool_creates_a_proposal_and_never_executes() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            registry=registry,
        )
        assert outcome.output["status"] == "pending_approval"
        assert outcome.output["tool_key"] == TIER1_TOOL_KEY
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))

        # Not executed during proposal.
        assert calls == []

        approvals = list_approvals(client.tenant_id)
        assert len(approvals) == 1
        approval = approvals[0]
        assert approval.id == approval_id
        assert approval.status == "pending"
        assert approval.tenant_id == client.tenant_id
        assert approval.proposer_user_id == owner.id
        assert approval.tool_key == TIER1_TOOL_KEY
        # The original tool arguments survive inside the proposal's own
        # payload -- what execute_approved() will need later.
        assert approval.payload["contact_id"] == str(contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_tier1_proposal_denied_for_unauthorized_actor_and_creates_no_approval() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        with pytest.raises(UnauthorizedToolInvocationError):
            await invoke_product_ai_tool(
                TIER1_TOOL_KEY,
                actor_user_id=stranger.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                registry=registry,
            )
        assert list_approvals(client.tenant_id) == []
        assert calls == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


async def test_tier1_proposal_denied_without_data_authorization_and_creates_no_approval() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls, requires_data_authorization=True))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        with pytest.raises(DataAuthorizationRequiredError):
            await invoke_product_ai_tool(
                TIER1_TOOL_KEY,
                actor_user_id=owner.id,
                tenant_id=client.tenant_id,
                resource_type="crm.contact",
                resource_id=str(contact.id),
                payload={"contact_id": str(contact.id)},
                registry=registry,
                # no tenant_policy -- default-deny, mirrors the tier-0
                # test_qualify_lead_denied_without_a_tenant_ai_policy case
            )
        assert list_approvals(client.tenant_id) == []
        assert calls == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- approve / reject ---------------------------------------------------------


async def test_approve_transitions_the_real_approval_and_is_tenant_scoped() -> None:
    owner = make_user()
    approver = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))

        approved = approve(client.tenant_id, approval_id, approver.id)
        assert approved.status == "approved"
        assert approved.tenant_id == client.tenant_id

        # tenant-scoped: fetching it back under its own real tenant works.
        refetched = get_approval(client.tenant_id, approval_id)
        assert refetched.status == "approved"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, approver.id)


async def test_rejected_approval_never_executes_and_tool_is_never_called() -> None:
    owner = make_user()
    approver = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))

        rejected = reject_approval(client.tenant_id, approval_id, approver.id)
        assert rejected.status == "rejected"

        with pytest.raises(ApprovalNotPendingError):
            await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert calls == []
        assert get_approval(client.tenant_id, approval_id).status == "rejected"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, approver.id)


# --- execute approved ---------------------------------------------------------


async def test_approved_tier1_tool_executes_exactly_once_through_the_real_tool_path() -> None:
    owner = make_user()
    approver = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))
        approve(client.tenant_id, approval_id, approver.id)

        executed = await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert executed.status == "executed"

        # Executed exactly once, with the original tool arguments preserved
        # (alongside the propose-time bookkeeping keys the handler itself
        # never looks at).
        assert len(calls) == 1
        assert calls[0]["contact_id"] == str(contact.id)

        # A second attempt against the same (now "executed") approval
        # must not execute the tool again.
        with pytest.raises(ApprovalNotPendingError):
            await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert len(calls) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, approver.id)


async def test_execute_approved_recomputes_data_authorization_fresh() -> None:
    """The Data Authorization decision is recomputed at execution time,
    from the proposal's own saved metadata -- never reused from, or
    trusted merely because of, proposal time. Proposing/approving with a
    permissive policy but executing with none (default-deny, as if the
    tenant's own policy had since been revoked) must still deny
    execution -- if the proposal-time decision were being reused instead
    of recomputed, this would incorrectly succeed."""
    owner = make_user()
    approver = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls, requires_data_authorization=True))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            tenant_policy=_permissive_policy(client.tenant_id, TIER1_TOOL_KEY),
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))
        approve(client.tenant_id, approval_id, approver.id)

        # No permissive policy supplied at execution time -- default-deny,
        # simulating the tenant's own policy having been revoked since
        # approval. _execute_tool() raises DataAuthorizationRequiredError
        # directly for this gate (never wrapped into ToolExecutionError --
        # that wrapping only applies to a handler's own exception).
        with pytest.raises(DataAuthorizationRequiredError):
            await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert calls == []
        # A failed execution rolls back to "approved", never stranded at
        # "executing" and never silently advanced to "executed".
        assert get_approval(client.tenant_id, approval_id).status == "approved"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, approver.id)


async def test_execution_failure_rolls_back_to_approved_with_no_duplicate_execution() -> None:
    owner = make_user()
    approver = make_user()
    agency, client = _agency_and_client(owner.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id), "force_fail": True},
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))
        approve(client.tenant_id, approval_id, approver.id)

        with pytest.raises(ToolExecutionError):
            await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert len(calls) == 1  # the handler *was* invoked once, and raised
        assert get_approval(client.tenant_id, approval_id).status == "approved"

        # A genuine retry remains possible -- exactly the existing
        # execute_approved() guarantee, unmodified.
        with pytest.raises(ToolExecutionError):
            await execute_approved_ai_tool(client.tenant_id, approval_id, registry=registry)
        assert len(calls) == 2  # retried, not silently treated as already-executed
        assert get_approval(client.tenant_id, approval_id).status == "approved"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, approver.id)


# --- cross-tenant isolation ----------------------------------------------------


async def test_approval_from_tenant_a_cannot_be_executed_as_tenant_b() -> None:
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(_build_tier1_tool(calls=calls))
    try:
        contact = create_contact(owner_a.id, client_a.tenant_id, first_name="A", last_name="B")
        outcome = await invoke_product_ai_tool(
            TIER1_TOOL_KEY,
            actor_user_id=owner_a.id,
            tenant_id=client_a.tenant_id,
            resource_type="crm.contact",
            resource_id=str(contact.id),
            payload={"contact_id": str(contact.id)},
            registry=registry,
        )
        approval_id = uuid.UUID(str(outcome.output["approval_id"]))

        with pytest.raises(ApprovalRequestNotFoundError):
            approve(client_b.tenant_id, approval_id, owner_b.id)
        with pytest.raises(ApprovalRequestNotFoundError):
            await execute_approved_ai_tool(client_b.tenant_id, approval_id, registry=registry)
        assert calls == []
        # Still perfectly usable under its own, real tenant.
        assert get_approval(client_a.tenant_id, approval_id).status == "pending"
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
