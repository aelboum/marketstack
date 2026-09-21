"""The complete Phase 9.4 production-readiness path against real,
disposable Postgres:

    tenant -> persisted AI policy -> Control Plane authorization
           -> Data Authorization -> approved tool -> provider abstraction

Marked `integration`, excluded from the default `pytest` run.

**Every allow-path test here supplies its own `ToolRegistry` built on
`FakeLLMProvider`.** That is not a shortcut around production: it is the
only honest way to exercise the chain, because no AI vendor has been
approved, so `product/ai/production.py` has no adapter to build a
production registry from and fails closed by design (proven separately
in `tests/ai/test_production_boundary_unit.py`). What these tests prove
is that the *policy and authorization* half of the production path is
real: a persisted, per-tenant, audited policy now decides what Data
Authorization allows, where Phase 9.1-9.3 hardcoded `None` for everyone.
"""

from __future__ import annotations

import uuid

import pytest
from control_plane.orchestration import ToolRegistry
from control_plane.orchestration.errors import (
    DataAuthorizationRequiredError,
    ToolExecutionError,
    UnauthorizedToolInvocationError,
)
from core.audit_log import list as list_audit_log
from product.agency.provisioning import provision_agency, provision_client
from product.ai.errors import AIAccessDeniedError, AIValidationError
from product.ai.invocation import invoke_product_ai_tool
from product.ai.policy import (
    get_tenant_ai_policy,
    resolve_tenant_ai_policy,
    set_tenant_ai_policy,
)
from product.ai.provider import FakeLLMProvider
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY
from product.ai.tools.lead_qualification import build_lead_qualification_tool
from product.crm.contacts import create_contact

from tests.ai._cleanup import cleanup_tenant_tree, cleanup_users, make_user

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


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(build_lead_qualification_tool(FakeLLMProvider()))
    return registry


def _approve(owner_id, tenant_id) -> None:
    set_tenant_ai_policy(
        owner_id,
        tenant_id,
        enabled=True,
        approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
        allowed_providers=("fake",),
    )


async def _invoke(owner_id, tenant_id, contact_id, *, registry=None):
    return await invoke_product_ai_tool(
        QUALIFY_LEAD_TOOL_KEY,
        actor_user_id=owner_id,
        tenant_id=tenant_id,
        resource_type="crm.contact",
        resource_id=str(contact_id),
        payload={"contact_id": str(contact_id)},
        registry=registry or _registry(),
    )


# --- policy CRUD, validation, isolation ------------------------------------


def test_policy_absent_by_default_and_resolves_to_none() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        assert get_tenant_ai_policy(owner.id, client.tenant_id) is None
        assert resolve_tenant_ai_policy(client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_set_then_read_policy_round_trip() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        view = set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=True,
            approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
            allowed_providers=("fake",),
        )
        assert view.enabled is True
        assert view.approved_capabilities == (QUALIFY_LEAD_TOOL_KEY,)
        assert view.updated_by_user_id == owner.id

        stored = get_tenant_ai_policy(owner.id, client.tenant_id)
        assert stored is not None
        assert stored.approved_capabilities == (QUALIFY_LEAD_TOOL_KEY,)

        resolved = resolve_tenant_ai_policy(client.tenant_id)
        assert resolved is not None
        assert resolved.tenant_id == client.tenant_id
        assert resolved.allowed_purposes == frozenset({QUALIFY_LEAD_TOOL_KEY})
        assert resolved.allowed_providers == frozenset({"fake"})
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_capability_is_rejected_and_nothing_is_persisted() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AIValidationError):
            set_tenant_ai_policy(
                owner.id,
                client.tenant_id,
                enabled=True,
                approved_capabilities=("ai.telephony.receptionist_advice",),
                allowed_providers=("fake",),
            )
        assert get_tenant_ai_policy(owner.id, client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_non_eligible_provider_is_rejected() -> None:
    """A tenant can narrow what the platform allows, never widen it."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AIValidationError):
            set_tenant_ai_policy(
                owner.id,
                client.tenant_id,
                enabled=True,
                approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
                allowed_providers=("some-unapproved-vendor",),
            )
        assert resolve_tenant_ai_policy(client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unauthorized_actor_cannot_read_or_mutate_policy() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AIAccessDeniedError):
            set_tenant_ai_policy(
                outsider.id,
                client.tenant_id,
                enabled=True,
                approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
                allowed_providers=("fake",),
            )
        with pytest.raises(AIAccessDeniedError):
            get_tenant_ai_policy(outsider.id, client.tenant_id)
        assert resolve_tenant_ai_policy(client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_tenant_a_policy_is_not_tenant_b_policy() -> None:
    """Security checkpoint: policies are per-tenant, and one tenant's
    approval never leaks into another's resolution."""
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _approve(owner_a.id, client_a.tenant_id)

        assert resolve_tenant_ai_policy(client_a.tenant_id) is not None
        assert resolve_tenant_ai_policy(client_b.tenant_id) is None
        assert get_tenant_ai_policy(owner_b.id, client_b.tenant_id) is None
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_tenant_a_actor_cannot_read_or_change_tenant_b_policy() -> None:
    """Security checkpoint: cross-tenant policy access fails safely."""
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _approve(owner_b.id, client_b.tenant_id)

        with pytest.raises(AIAccessDeniedError):
            get_tenant_ai_policy(owner_a.id, client_b.tenant_id)
        with pytest.raises(AIAccessDeniedError):
            set_tenant_ai_policy(
                owner_a.id,
                client_b.tenant_id,
                enabled=False,
                approved_capabilities=(),
                allowed_providers=(),
            )
        # tenant B's policy is untouched by the attempt
        still = get_tenant_ai_policy(owner_b.id, client_b.tenant_id)
        assert still is not None and still.enabled is True
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_policy_mutation_is_audited_with_bounded_metadata() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _approve(owner.id, client.tenant_id)
        entries = list_audit_log(
            client.tenant_id, resource_type="ai.policy", resource_id=str(client.tenant_id)
        )
        updates = [e for e in entries if e.action == "ai.policy.updated"]
        assert updates
        # NOTE: the attribute is `entry_metadata`, not `metadata` --
        # `AuditLogEntry.metadata` is SQLAlchemy's own declarative
        # `MetaData` object (a name collision on every ORM model), so
        # asserting against `.metadata` silently tests nothing.
        metadata = updates[-1].entry_metadata or {}
        assert metadata.get("enabled") is True
        assert metadata.get("approved_capabilities") == [QUALIFY_LEAD_TOOL_KEY]
        # bounded identifiers only -- no prompt, no completion, no record content
        assert set(metadata) <= {"enabled", "approved_capabilities", "allowed_providers"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- the Data Authorization production path --------------------------------


async def test_no_policy_denies_execution() -> None:
    """Required case 1: no policy -> denied."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        with pytest.raises(DataAuthorizationRequiredError):
            await _invoke(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_disabled_tenant_policy_denies_execution() -> None:
    """Required case 2: disabled tenant -> denied."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=False,
            approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
            allowed_providers=("fake",),
        )
        assert resolve_tenant_ai_policy(client.tenant_id) is None
        with pytest.raises(DataAuthorizationRequiredError):
            await _invoke(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_unapproved_capability_denies_execution() -> None:
    """Required case 3: enabled policy that does not approve *this*
    capability -> denied. Proven by approving the capability and then
    revoking it, so the only difference is the approval itself."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        await _invoke(owner.id, client.tenant_id, contact.id)  # allowed

        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=True,
            approved_capabilities=(),
            allowed_providers=("fake",),
        )
        with pytest.raises(DataAuthorizationRequiredError):
            await _invoke(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_approved_capability_and_authorized_resource_is_allowed() -> None:
    """Required case 4: the one allow path -- reached only after every
    prior check passes explicitly."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="L")
        _approve(owner.id, client.tenant_id)

        provider = FakeLLMProvider()
        registry = ToolRegistry()
        registry.register(build_lead_qualification_tool(provider))

        outcome = await _invoke(owner.id, client.tenant_id, contact.id, registry=registry)
        assert outcome.output["contact_id"] == str(contact.id)
        assert outcome.output["provider"] == "fake"
        assert provider.requests  # the provider abstraction was actually used
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_cross_tenant_resource_is_denied() -> None:
    """Required case 5 / security checkpoint: tenant A's approved policy
    does not let tenant A's actor reach tenant B's contact."""
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _approve(owner_a.id, client_a.tenant_id)
        _approve(owner_b.id, client_b.tenant_id)
        b_contact = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="B")

        # A's actor, A's tenant, but B's contact id -- the tool's own
        # tenant-scoped read cannot resolve it, so the handler raises and
        # the Control Plane surfaces it as a ToolExecutionError. The
        # contact is never read, and nothing about it reaches a provider.
        with pytest.raises(ToolExecutionError):
            await _invoke(owner_a.id, client_a.tenant_id, b_contact.id)

        # A's actor against B's tenant is refused by RBAC before any read.
        with pytest.raises(UnauthorizedToolInvocationError):
            await _invoke(owner_a.id, client_b.tenant_id, b_contact.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


async def test_unauthorized_actor_is_denied_even_with_an_approved_policy() -> None:
    """Required case 6: an approved tenant policy is not a substitute for
    the actor's own authorization."""
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        with pytest.raises(UnauthorizedToolInvocationError):
            await _invoke(outsider.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


async def test_denied_and_allowed_decisions_are_both_audited() -> None:
    """Required cases 7 and 8: existing Control Plane audit behaviour is
    reused unchanged -- this phase adds no parallel audit path."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")

        with pytest.raises(DataAuthorizationRequiredError):
            await _invoke(owner.id, client.tenant_id, contact.id)
        after_deny = list_audit_log(client.tenant_id)
        assert after_deny

        _approve(owner.id, client.tenant_id)
        await _invoke(owner.id, client.tenant_id, contact.id)
        after_allow = list_audit_log(client.tenant_id)
        assert len(after_allow) > len(after_deny)

        # No audit entry carries model output or prompt content. Reads
        # `entry_metadata` deliberately -- see the note in
        # `test_policy_mutation_is_audited_with_bounded_metadata` on why
        # `.metadata` would assert against SQLAlchemy's own object instead.
        for entry in after_allow:
            rendered = str(entry.entry_metadata or {})
            assert "FAKE_LLM_COMPLETION" not in rendered
            assert "Ada" not in rendered
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_policy_revocation_takes_effect_on_the_next_invocation() -> None:
    """No caching, no module-level policy state: a policy revoked between
    one invocation and the next denies the next one."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        await _invoke(owner.id, client.tenant_id, contact.id)

        set_tenant_ai_policy(
            owner.id,
            client.tenant_id,
            enabled=False,
            approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
            allowed_providers=("fake",),
        )
        with pytest.raises(DataAuthorizationRequiredError):
            await _invoke(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
