"""The complete Phase 10.4A production path against real, disposable
Postgres:

    Automation action registry (product.foundation.workflow_actions)
        -> product.ai.automation_action (the ai.crm.qualify_lead adapter)
        -> product.ai.invocation.invoke_product_ai_tool()
        -> product.ai.production.production_tool_registry()
        -> Control Plane authorization (RBAC/tier) + Data Authorization
        -> product.ai.tools.lead_qualification's own handler

Marked `integration`, excluded from the default `pytest` run.

**A non-"fake"-named test double provider is registered for this file's
own authorization-matrix tests, on purpose.** `_execute()`
(`product/ai/automation_action.py`) always calls
`production_tool_registry()` -- unlike Phase 9.4's own tests, it accepts
no injectable `registry=` override -- so exercising the REAL production
path (not merely the generic Control-Plane invocation path Phase 9.4
already proved) requires a provider `register_production_llm_provider()`
will actually accept. `_TestDoubleProvider` below delegates to a real
`FakeLLMProvider` internally (deterministic, no network) but is named
`"integration-test-double"` -- not `"fake"`/`"stub"`/`"mock"`/`"test"` --
so it is NOT refused by the exact-name check that exists specifically to
keep the *real* `FakeLLMProvider` from ever becoming production
(`product/ai/production.py`'s own module docstring). This is not a claim
that a real vendor is configured; it exists only to prove
`production_tool_registry()`'s own real code path (provider lookup, tool
building, registry construction) executes correctly end to end.

**Platform-wide provider eligibility is also widened, test-scope only,
for the identical reason.** `product.ai.policy.PLATFORM_PROVIDER_POLICY`
hardcodes `eligible_providers={"fake"}` -- no real vendor has been
approved for this product (that module's own docstring) -- and `"fake"`
can never be the *production* provider either, so with no override at
all, a tenant policy could never legally approve any provider name that
could also pass as this adapter's own production provider, and the
allow-path could never be reached through the *real* adapter (only
through Phase 9.4's own tests, which inject a registry directly and
bypass `production_tool_registry()` entirely). The `_platform_provider_eligible`
fixture below monkeypatches the frozenset in both places it is bound --
`product.ai.policy` (read by `set_tenant_ai_policy()`'s own validation)
and `product.ai.invocation` (a separate `from ... import` binding, read
by `invoke_product_ai_tool()`) -- reverted automatically after every
test. This proves the wiring is correct for when a real vendor's name
is eventually added to that list; it does not claim one exists today,
and never touches the real, persisted policy outside this test process.
"""

from __future__ import annotations

import uuid

import pytest
from control_plane.data_authorization import ProviderEligibilityPolicy
from core.audit_log import list as list_audit_log
from product.agency.provisioning import provision_agency, provision_client
from product.ai.automation_action import build_qualify_lead_workflow_action
from product.ai.policy import set_tenant_ai_policy
from product.ai.production import (
    clear_production_llm_provider,
    register_production_llm_provider,
)
from product.ai.provider import FakeLLMProvider, LLMCompletion
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY
from product.automation.actions import ACTION_AI_QUALIFY_LEAD, execute_action
from product.crm.contacts import create_contact
from product.foundation.workflow_actions import (
    WorkflowActionDeniedError,
    WorkflowActionExecutionError,
)

from tests.ai._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


class _TestDoubleProvider:
    """See module docstring -- deliberately NOT named "fake"/"stub"/
    "mock"/"test", so `register_production_llm_provider()` accepts it,
    while its own `.complete()` delegates to a real `FakeLLMProvider` for
    genuinely deterministic, network-free output."""

    def __init__(self) -> None:
        self._delegate = FakeLLMProvider()

    @property
    def name(self) -> str:
        return "integration-test-double"

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        inner = self._delegate.complete(
            system_prompt=system_prompt,
            user_content=user_content,
            max_output_chars=max_output_chars,
        )
        return LLMCompletion(text=inner.text, provider_name=self.name)


@pytest.fixture(autouse=True)
def _production_provider(monkeypatch):
    widened = ProviderEligibilityPolicy(eligible_providers=frozenset({"integration-test-double"}))
    monkeypatch.setattr("product.ai.policy.PLATFORM_PROVIDER_POLICY", widened)
    monkeypatch.setattr("product.ai.invocation.PLATFORM_PROVIDER_POLICY", widened)
    clear_production_llm_provider()
    register_production_llm_provider(_TestDoubleProvider())
    yield
    clear_production_llm_provider()


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _approve(owner_id, tenant_id) -> None:
    set_tenant_ai_policy(
        owner_id,
        tenant_id,
        enabled=True,
        approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
        allowed_providers=("integration-test-double",),
    )


def _spec_execute(actor_id, tenant_id, contact_id):
    spec = build_qualify_lead_workflow_action()
    return spec.execute(actor_id, tenant_id, {}, {"contact_id": str(contact_id)})


# --- the eight required authorization-matrix cases --------------------


def test_no_policy_denies() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_disabled_tenant_policy_denies() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=False,
            approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
            allowed_providers=("integration-test-double",),
        )
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capability_not_approved_denies() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=True,
            approved_capabilities=(),  # enabled, but this capability not in the list
            allowed_providers=("integration-test-double",),
        )
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_allowed_capability_and_authorized_resource_proceeds() -> None:
    """Required case: the one allow path, exercised through the real
    adapter and the real `production_tool_registry()`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="L")
        _approve(owner.id, client.tenant_id)
        result = _spec_execute(owner.id, client.tenant_id, contact.id)
        assert result["contact_id"] == str(contact.id)
        assert result["provider"] == "integration-test-double"
        assert result["qualification"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_policy_revocation_before_execution_denies() -> None:
    """Execution-time authorization: a policy revoked between publish and
    execution denies the later attempt, never relying on a decision
    captured earlier."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        _spec_execute(owner.id, client.tenant_id, contact.id)  # succeeds once

        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=False,
            approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
            allowed_providers=("integration-test-double",),
        )
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unauthorized_actor_denies() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(outsider.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_cross_tenant_contact_denies() -> None:
    """Required case: a cross-tenant contact id must not be usable to
    escape tenant isolation. The actor's own tenant scoping already
    prevents the contact row from resolving at all (RLS + the tool
    handler's own tenant-scoped `get_contact()` lookup), which
    `control_plane.orchestration`'s own `_execute_tool()` normalizes into
    a generic `ToolExecutionError` -- this adapter maps that to
    `WorkflowActionExecutionError` (see `product/ai/automation_action.py`'s
    own module docstring on why this lands in the execution-failure
    bucket, not the denial bucket). The security property under test is
    unaffected by which of the two neutral buckets it lands in: the
    action never reads, and never qualifies, another tenant's contact."""
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _approve(owner_a.id, client_a.tenant_id)
        b_contact = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="B")
        with pytest.raises(WorkflowActionExecutionError):
            _spec_execute(owner_a.id, client_a.tenant_id, b_contact.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_tenant_lifecycle_purge_denies() -> None:
    """Required case: a purged tenant's own approved AI action can no
    longer execute -- proven the same way Phase 10.3's own
    `test_purge_terminates_active_run_and_prevents_resume` proves it for
    durable runs, applied here to this specific action. No new lifecycle
    logic is added: this reuses the existing `core.tenancy` transition +
    purge machinery unchanged, plus the existing `AIDataPurgeParticipant`
    (`product/ai/purge.py`, registered by Phase 9.4)."""
    from core.tenancy import TenantStatus, purge_tenant, transition_tenant_status
    from core.tenancy.purge_participants import TenantPurgeParticipantRegistry
    from product.ai.purge import AIDataPurgeParticipant
    from product.crm.purge import CrmDataPurgeParticipant

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        _spec_execute(owner.id, client.tenant_id, contact.id)  # succeeds before purge

        registry = TenantPurgeParticipantRegistry()
        registry.register(AIDataPurgeParticipant())
        registry.register(CrmDataPurgeParticipant())

        transition_tenant_status(client.tenant_id, TenantStatus.DELETED, actor_user_id=owner.id)
        transition_tenant_status(client.tenant_id, TenantStatus.PURGING, actor_user_id=owner.id)
        purge_tenant(client.tenant_id, actor_user_id=owner.id, registry=registry)

        # Which specific exception fires is itself defense in depth
        # (mirrors `tests/automation/durable/production
        # /test_execution_temporal.py::test_purge_terminates_active_run_
        # and_prevents_resume`'s own identical reasoning): `purge_tenant()`
        # removes this tenant's own RBAC rows, so the underlying
        # `crm.contact:read` check denies before any lookup even happens
        # (`UnauthorizedToolInvocationError` -> `WorkflowActionDeniedError`);
        # if a grant somehow survived, the contact row itself is gone
        # (`CrmDataPurgeParticipant`), so the read fails instead
        # (`ToolExecutionError` -> `WorkflowActionExecutionError`). Either
        # outcome proves the purged tenant's own AI action cannot execute.
        with pytest.raises((WorkflowActionDeniedError, WorkflowActionExecutionError)):
            _spec_execute(owner.id, client.tenant_id, contact.id)
    finally:
        # `purge_tenant()` does not delete the `core.tenants` row itself
        # (identical precedent to the durable-engine purge test cited
        # above) -- both tenants still need leaf-to-root teardown;
        # cleanup_tenant_tree() is itself idempotent against already-empty
        # tables.
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Automation's own generic dispatch reaches the same adapter --------


def test_automation_execute_action_resolves_and_executes_the_ai_action() -> None:
    """No special-case branch in Automation: `execute_action()` resolves
    `ACTION_AI_QUALIFY_LEAD` through the same generic registry lookup
    every other action goes through (`product/automation/actions.py
    ::execute_action()` -- unmodified in this phase beyond the defensive
    `UnknownWorkflowActionError` catch already present for every action)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="L")
        _approve(owner.id, client.tenant_id)
        result = execute_action(
            ACTION_AI_QUALIFY_LEAD,
            owner.id,
            client.tenant_id,
            {},
            {"contact_id": str(contact.id)},
        )
        assert result["contact_id"] == str(contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- audit --------------------------------------------------------------


def test_denied_execution_is_audited_via_existing_mechanism() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        before = list_audit_log(client.tenant_id)
        with pytest.raises(WorkflowActionDeniedError):
            _spec_execute(owner.id, client.tenant_id, contact.id)
        after = list_audit_log(client.tenant_id)
        assert len(after) > len(before)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_successful_execution_is_audited_with_no_sensitive_payload() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        secret_email = f"probe-{uuid.uuid4().hex[:8]}@example.invalid"
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace", email=secret_email
        )
        _approve(owner.id, client.tenant_id)
        before = list_audit_log(client.tenant_id)
        _spec_execute(owner.id, client.tenant_id, contact.id)
        after = list_audit_log(client.tenant_id)
        assert len(after) > len(before)
        for entry in after:
            rendered = str(entry.entry_metadata or {})
            assert secret_email not in rendered
            assert "Lovelace" not in rendered
            assert "FAKE_LLM_COMPLETION" not in rendered
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
