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
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from control_plane.data_authorization import (
    DataAuthorizationDecision,
    DataAuthorizationRequest,
    TenantAIDataPolicy,
    authorize_data_access,
)
from control_plane.orchestration import ToolInvocationResult, ToolRegistry, invoke_tool
from control_plane.orchestration.tools import default_registry

from product.ai.policy import PLATFORM_PROVIDER_POLICY, resolve_tenant_ai_policy


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
    (`ToolNotFoundError`), a tier>=1 tool (`TierRequiresApprovalError`),
    a failed RBAC check (`UnauthorizedToolInvocationError`), or a denied
    Data Authorization gate (`DataAuthorizationRequiredError`) -- this
    module never catches or re-wraps any of them (Phase 9's own "do not
    create Product-local equivalents" requirement).

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

    return await invoke_tool(
        tool_key,
        agent_user_id=actor_user_id,
        tenant_id=tenant_id,
        payload=payload,
        registry=registry,
        data_authorization_decision=decision,
    )


__all__ = ["invoke_product_ai_tool"]
