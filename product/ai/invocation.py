"""The one entrypoint Product code uses to invoke a `product/ai/tools/*.py`
tool -- wires `control_plane.data_authorization` ahead of
`control_plane.orchestration.invoke_tool()` so every tool declaring
`requires_data_authorization=True` is genuinely gated, not merely capable
of being gated (docs/ROADMAP.md Phase 9.1's "no exceptions, no
'temporary' direct calls" requirement).

**Never calls a tool's handler directly, never re-implements RBAC/tier/
audit** -- this module is a thin composition of two already-audited
SaaS-OS entrypoints (`control_plane.data_authorization.authorize_data_access()`,
`control_plane.orchestration.invoke_tool()`), in the order Phase 9's own
instructions require (RBAC/tier first, inside `invoke_tool()` itself, then
Data Authorization, per `control_plane.orchestration.service._execute_tool()`'s
own documented check order) -- never a Product-local competing
authorization/control plane.

**`tenant_policy` defaults to `product.ai.policy.resolve_tenant_ai_policy()`**
(always `None` today -- see that module's own docstring), so a caller
never has to remember to look one up; a test that wants to exercise the
ALLOW path supplies an explicit, permissive `TenantAIDataPolicy` instead.

**Tier>=1 approval integration (docs/ROADMAP.md Phase 26B).** A tool
declaring `autonomy_tier >= 1` is never executed directly here -- it is
staged through the existing, unmodified `control_plane.approvals
.propose_action()` instead of raising `TierRequiresApprovalError`. This
is not a second approval mechanism: `propose_action()`/`approve()`/
`reject()`/`execute_approved()` are the *same* SaaS-OS functions
`tests/approvals/test_approval_inbox_integration.py` and
`product/approvals/service.py` (Phase 29's own Approval Inbox) already
exercise; this module only decides *when* to call `propose_action()`
instead of `invoke_tool()`, using the tool's own already-public
`autonomy_tier` field, never a new state machine or a new persisted
model. `qualify_lead` remains `autonomy_tier=0` and is entirely
unaffected -- the branch below is simply never taken for it.

**Proposal-time authorization mirrors tier-0 exactly, computed before
`propose_action()` is ever called**: the same RBAC check `invoke_tool()`
would perform (`core.rbac.can()` against the tool's own public
`required_resource`/`required_action`, mirroring
`control_plane.orchestration.service._is_authorized()`'s tenant-scope
branch -- the only branch this module has ever supported, tier-0 or
tier>=1) and the same Data Authorization decision this module already
computes unconditionally above. Passing neither gate ever creates a
proposal -- `UnauthorizedToolInvocationError`/`DataAuthorizationRequiredError`
are raised exactly as `invoke_tool()`/`_execute_tool()` already raise them
for tier-0, never a Product-local equivalent. Approval is strictly an
additional execution-control layer on top of these checks, never a
substitute for them.

**No recursion.** `execute_approved_ai_tool()` below calls
`control_plane.approvals.execute_approved()`, which calls
`control_plane.orchestration.service._execute_tool()` *directly* -- the
same private entrypoint `execute_approved()` itself already uses to
bypass `invoke_tool()`'s tier>=1 refusal. It never calls back into
`invoke_tool()` or `invoke_product_ai_tool()`, so there is no
propose -> execute -> propose -> ... cycle to guard against."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import cast

from control_plane.approvals import ApprovalRequest, execute_approved, get_approval, propose_action
from control_plane.data_authorization import (
    DataAuthorizationDecision,
    DataAuthorizationOutcome,
    DataAuthorizationRequest,
    TenantAIDataPolicy,
    authorize_data_access,
    verify_data_authorization_provenance,
)
from control_plane.orchestration import (
    DataAuthorizationRequiredError,
    ToolInvocationResult,
    ToolRegistry,
    UnauthorizedToolInvocationError,
    invoke_tool,
)
from control_plane.orchestration.tools import ToolDefinition, default_registry
from core.rbac import can as rbac_can

from product.ai.policy import PLATFORM_PROVIDER_POLICY, resolve_tenant_ai_policy

#: Reserved `ApprovalRequest.payload` keys carrying what
#: `execute_approved_ai_tool()` needs to recompute a *fresh* Data
#: Authorization decision at execution time -- stored alongside the real
#: tool payload rather than as new `ApprovalRequest` columns (the model's
#: own "a plain JSON dict, no fixed schema" design, docs/ROADMAP.md Phase
#: 26B's own "use the existing payload/action fields" requirement).
#: Double-underscore-wrapped so they cannot collide with any real tool
#: payload field -- no existing or plausible future tool payload key uses
#: this shape (every existing tool reads plain identifiers like
#: `contact_id`/`thread_id`/`opportunity_id`).
_RESOURCE_TYPE_KEY = "__ai_resource_type__"
_RESOURCE_ID_KEY = "__ai_resource_id__"
_PROVIDER_NAME_KEY = "__ai_provider_name__"


def _tool_authorized(
    tool: ToolDefinition, *, actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> bool:
    """The identical RBAC check `control_plane.orchestration.service
    ._is_authorized()` performs for its tenant-scope branch -- the only
    branch `product/ai/invocation.py` has ever supported (every call here
    already omits `agent_scope_value`, so an environment/repository-scoped
    tool could never pass `invoke_tool()`'s own check either; this mirrors
    that existing, implicit assumption rather than introducing a new
    one). Reused via the same public `core.rbac.can()` Policy Engine
    entrypoint `_is_authorized()` itself calls -- `_is_authorized()` is a
    private orchestration function, not imported here."""
    assert tool.required_resource is not None
    assert tool.required_action is not None
    return rbac_can(
        actor_id=actor_user_id,
        tenant_id=tenant_id,
        action=tool.required_action,
        resource=tool.required_resource,
    )


def _data_authorization_allowed(
    decision: DataAuthorizationDecision | None, *, tenant_id: uuid.UUID
) -> bool:
    """Mirrors `control_plane.orchestration.service
    ._data_authorization_satisfied()` exactly (that function is private;
    this module already computes its own `decision` via the same public
    `authorize_data_access()` call `_execute_tool()` itself never makes)."""
    return (
        decision is not None
        and decision.tenant_id == tenant_id
        and decision.outcome is DataAuthorizationOutcome.ALLOW
        and verify_data_authorization_provenance(decision, tenant_id=tenant_id)
    )


def _propose_tier_gated_tool(
    tool: ToolDefinition,
    *,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resource_type: str,
    resource_id: str | None,
    payload: Mapping[str, object] | None,
    provider_name: str,
    decision: DataAuthorizationDecision | None,
) -> ToolInvocationResult:
    """Stage `tool` for approval instead of executing it -- the tier>=1
    branch of `invoke_product_ai_tool()` below. Never executes the tool;
    never calls the provider. Raises exactly what `invoke_tool()`/
    `_execute_tool()` would raise for the same failure at tier 0, so a
    caller cannot tell, from the exception alone, that a proposal was
    even attempted."""
    if not _tool_authorized(tool, actor_user_id=actor_user_id, tenant_id=tenant_id):
        raise UnauthorizedToolInvocationError(tool.key)
    if tool.requires_data_authorization and not _data_authorization_allowed(
        decision, tenant_id=tenant_id
    ):
        raise DataAuthorizationRequiredError(tool.key)

    approval_payload: dict[str, object] = dict(payload or {})
    approval_payload[_RESOURCE_TYPE_KEY] = resource_type
    approval_payload[_RESOURCE_ID_KEY] = resource_id
    approval_payload[_PROVIDER_NAME_KEY] = provider_name

    approval = propose_action(tenant_id, actor_user_id, tool.key, payload=approval_payload)
    return ToolInvocationResult(
        tool_key=tool.key,
        correlation_id=str(approval.id),
        output={
            "status": "pending_approval",
            "approval_id": str(approval.id),
            "tool_key": tool.key,
        },
    )


async def invoke_product_ai_tool(
    tool_key: str,
    *,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resource_type: str,
    resource_id: str | None = None,
    payload: Mapping[str, object] | None = None,
    provider_name: str = "fake",
    tenant_policy: TenantAIDataPolicy | None = None,
    registry: ToolRegistry | None = None,
) -> ToolInvocationResult:
    """Raises whatever `control_plane.orchestration.invoke_tool()`/
    `_execute_tool()` itself raises for an unregistered tool
    (`ToolNotFoundError`), a failed RBAC check
    (`UnauthorizedToolInvocationError`), or a denied Data Authorization
    gate (`DataAuthorizationRequiredError`) -- this module never catches
    or re-wraps any of them (Phase 9's own "do not create Product-local
    equivalents" requirement). A tier>=1 tool no longer raises
    `TierRequiresApprovalError` (module docstring's own "Tier>=1 approval
    integration" section) -- it is proposed instead, returning a
    `ToolInvocationResult` whose `output` deterministically describes the
    pending approval rather than a real tool result.

    `tenant_policy`: omit (default `None`) to fall back to
    `product.ai.policy.resolve_tenant_ai_policy()` (always `None` today,
    so every data-authorization-requiring tool is denied by default --
    no behavioral difference between "omitted" and "explicitly `None`"
    exists today for that reason); pass an explicit `TenantAIDataPolicy`
    (only ever done by a test) to exercise the allow path."""
    active_registry = registry or default_registry()
    tool = active_registry.get(tool_key)

    decision: DataAuthorizationDecision | None = None
    if tool.requires_data_authorization:
        resolved_policy = (
            tenant_policy if tenant_policy is not None else resolve_tenant_ai_policy(tenant_id)
        )
        request = DataAuthorizationRequest(
            tenant_id=tenant_id,
            data_classification=tool.data_classification,
            purpose=tool.key,
            provider=provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        decision = authorize_data_access(
            request,
            tenant_policy=resolved_policy,
            provider_policy=PLATFORM_PROVIDER_POLICY,
            actor_user_id=actor_user_id,
        )

    if tool.autonomy_tier >= 1:
        return _propose_tier_gated_tool(
            tool,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            provider_name=provider_name,
            decision=decision,
        )

    return await invoke_tool(
        tool_key,
        agent_user_id=actor_user_id,
        tenant_id=tenant_id,
        payload=payload,
        registry=registry,
        data_authorization_decision=decision,
    )


async def execute_approved_ai_tool(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    tenant_policy: TenantAIDataPolicy | None = None,
    registry: ToolRegistry | None = None,
) -> ApprovalRequest:
    """Execute a previously-approved tier>=1 AI tool proposal.

    Reuses `control_plane.approvals.execute_approved()` completely
    unmodified for the actual claim/execute/rollback machinery -- this
    function's only job is to recompute a *fresh* Data Authorization
    decision, from the `resource_type`/`resource_id`/`provider_name`
    stashed in the proposal's own `payload` at propose time
    (`_propose_tier_gated_tool()` above), immediately before that call.
    `execute_approved()` -> `_execute_tool()` itself already re-runs RBAC
    fresh, using the *proposer's* identity, exactly as it does for tier 0
    -- never duplicated here (docs/ROADMAP.md Phase 26B's own "approval
    must not grant permission the original invocation would not have; do
    not rely solely on the fact that an action was previously approved"
    requirement).

    `tenant_policy`: same convention as `invoke_product_ai_tool()`'s own
    parameter of the same name -- omit (default `None`) to fall back to
    `product.ai.policy.resolve_tenant_ai_policy()`; pass an explicit
    `TenantAIDataPolicy` (only ever done by a test) to exercise the allow
    path for a tool whose `tool_key` is not one of the closed
    `PRODUCTION_CAPABILITIES` `set_tenant_ai_policy()` itself validates
    against.

    Distinct from `product/approvals/service.py::execute_approval()`
    (Phase 29's Approval Inbox), which always passes
    `data_authorization_decision=None` by its own documented design --
    correct for that surface's own scope, but meaning a tool declaring
    `requires_data_authorization=True` can never execute through it. This
    function exists specifically so an AI capability *can*, without
    reopening or modifying that Phase 29 surface."""
    active_registry = registry or default_registry()
    approval = get_approval(tenant_id, approval_id)
    tool = active_registry.get(approval.tool_key)

    decision: DataAuthorizationDecision | None = None
    if tool.requires_data_authorization:
        # Cast, not validate: these three keys are never caller/API-supplied
        # -- they exist only because `_propose_tier_gated_tool()` wrote them,
        # with these exact types, as this same proposal's own payload.
        resource_type = cast(str, approval.payload.get(_RESOURCE_TYPE_KEY))
        resource_id = cast("str | None", approval.payload.get(_RESOURCE_ID_KEY))
        provider_name = cast(str, approval.payload.get(_PROVIDER_NAME_KEY, "fake"))
        resolved_policy = (
            tenant_policy if tenant_policy is not None else resolve_tenant_ai_policy(tenant_id)
        )
        request = DataAuthorizationRequest(
            tenant_id=tenant_id,
            data_classification=tool.data_classification,
            purpose=tool.key,
            provider=provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        decision = authorize_data_access(
            request,
            tenant_policy=resolved_policy,
            provider_policy=PLATFORM_PROVIDER_POLICY,
            actor_user_id=approval.proposer_user_id,
        )

    return await execute_approved(
        tenant_id, approval_id, registry=registry, data_authorization_decision=decision
    )


__all__ = ["execute_approved_ai_tool", "invoke_product_ai_tool"]
