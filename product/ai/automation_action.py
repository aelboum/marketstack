"""The `ai.crm.qualify_lead` Automation workflow-action adapter
(docs/ROADMAP.md Phase 10.4A) -- the one AI-owned implementation of the
neutral `product.foundation.workflow_actions.WorkflowAction` contract
established by Phase 10.3A.

**Lives in `product.ai`, never imported by `product.automation`.** The
import-linter contracts forbid `product.automation -> product.ai` (and
the reverse) -- see `product/foundation/workflow_actions.py`'s own module
docstring for the full reasoning. This module therefore never imports
anything from `product.automation`, and nothing in `product.automation`
imports this module either. The two sides meet only at
`product/action_registry_composition.py`, the one place explicitly
allowed to know about both.

**Uses exactly the Phase 9.4 production path, unchanged.** `execute()`
below calls straight into `product.ai.invocation.invoke_product_ai_tool()`
against `product.ai.production.production_tool_registry()` -- the SAME
tenant-policy resolution, RBAC/tier check, and Data Authorization gate
every other caller of that path already goes through
(`docs/ROADMAP.md` Phase 9.4). `provider_name=` is passed explicitly as
the *actual* configured production provider's own name (never the
`invoke_product_ai_tool()` default of `"fake"`) -- otherwise the Data
Authorization request would always name `"fake"` regardless of what
`production_tool_registry()` really built the tool against, making a
tenant's own `allowed_providers` policy field meaningless. This adapter performs **no authorization
of its own** -- it never calls `core.rbac.can()`, never inspects a tenant
policy directly, and never caches a decision. Every production-readiness
authorization gate (`product/ai/production.py`'s own module docstring:
tenant policy resolution, RBAC, tier, Data Authorization, production
capability allow-list, provider availability) is re-evaluated **fresh, on
every call**, using the `actor_user_id`/`tenant_id` the durable run or
10.2 dispatcher passes in at that exact moment -- never an identity or
decision captured when the workflow was published or started.

**Bounded configuration, no prompt-injection surface.** `action_config`
for this action carries no fields at all -- the capability, the tenant,
the resource, and the prompt are all fixed by
`product/ai/tools/lead_qualification.py`'s own tool definition; nothing
in a workflow definition can select a different capability, a different
provider, or a different prompt. The only dynamic input is
`payload["contact_id"]` (a CRM contact identifier), read the same way
`product/automation/actions.py::_execute_update_contact()` already reads
`contact_id` from the triggering event's own payload -- never from
static config, and never a raw transcript, name, email, or phone number.

**Retry/error classification, mapped once, matching existing precedent
exactly** (see each `except` clause below for the specific reasoning):
Control-Plane authorization/tier/Data-Authorization denials, and a
closed/suspended/deleted/purging/purged or nonexistent tenant
(`core.tenancy`'s own existing lifecycle fence,
`control_plane.orchestration.service._execute_tool()`'s own
`require_open_tenant()` check -- not duplicated here, only reacted to),
all become `WorkflowActionDeniedError` (permanent -- matches how
`AutomationAccessDeniedError`/`CrmAccessDeniedError` are already
classified in `product/automation/durable/business_activities.py`). A
missing or malformed `contact_id` in the payload, an unconfigured
production provider, or a generic `ToolExecutionError`/`ToolNotFoundError`
from the Control Plane all become `WorkflowActionExecutionError` (the
*potentially transient* bucket the durable engine's own bounded
`RetryPolicy` already applies to `AutomationActionError` today).
`control_plane.orchestration`'s own `_execute_tool()` normalizes a
handler failure into one generic `ToolExecutionError`, discarding whether
the original cause (e.g. "contact not found in this tenant") was itself
permanent -- so this adapter cannot reliably tell "permanent" apart from
"transient" here, and does not invent a guarantee it cannot back up,
exactly the same granularity `send_webhook`'s own `httpx.HTTPError`
handling already accepts for an ambiguous provider-side failure in this
same codebase. Bounded either way: the durable engine's own `RetryPolicy`
is bounded, never infinite, so a genuinely permanent cause classified as
"potentially transient" still fails and stops, it just does so after a
few bounded attempts rather than immediately.

**Safe to bridge sync -> async here.** `WorkflowAction.execute()` is a
plain, synchronous method; `invoke_product_ai_tool()` is `async def`.
Both existing callers of `execute()` already run on a plain worker thread
with no event loop of its own: the 10.2 synchronous dispatcher's own
event-publisher call stack (every CRM route that publishes a triggering
event is a plain `def`, dispatched by FastAPI's own threadpool for sync
handlers) and the Temporal durable activity's own `activity_executor`
threadpool (`product/automation/durable/production_worker.py`'s own
module docstring) -- identical reasoning to
`product/automation/purge.py`'s own `asyncio.run()` bridge, which is
safe there for the same reason.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping

from control_plane.orchestration.errors import (
    DataAuthorizationRequiredError,
    TierRequiresApprovalError,
    ToolExecutionError,
    ToolNotFoundError,
    UnauthorizedToolInvocationError,
)
from core.tenancy.errors import TenantClosedError, TenantNotFoundError

from product.ai.errors import AIProviderNotConfiguredError, AIValidationError
from product.ai.invocation import invoke_product_ai_tool
from product.ai.production import get_production_llm_provider, production_tool_registry
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY
from product.foundation.workflow_actions import (
    ActionConfig,
    ActionPayload,
    ActionResult,
    WorkflowActionConfigError,
    WorkflowActionDeniedError,
    WorkflowActionExecutionError,
    WorkflowActionSpec,
)

#: The one production AI capability this adapter exposes to Automation.
#: Must equal `product.automation.actions.ACTION_AI_QUALIFY_LEAD` exactly
#: -- neither side imports the other's constant (that import is
#: forbidden), so `tests/ai/test_automation_action_unit.py` asserts the
#: two literals stay equal, and `WorkflowActionRegistry.register()` itself
#: refuses a mismatch at composition time regardless
#: (`UnknownWorkflowActionError` if this name is not in Automation's own
#: declared vocabulary).
ACTION_NAME = QUALIFY_LEAD_TOOL_KEY


def _validate_config(config: ActionConfig) -> None:
    """No configurable fields at all -- see module docstring's own
    "Bounded configuration" section. Any key at all is rejected, closing
    off the one place a workflow author could otherwise try to smuggle in
    a custom prompt, model, or provider selection."""
    if config:
        raise WorkflowActionConfigError(
            f"{ACTION_NAME} takes no action_config fields; got {sorted(config)}. "
            f"The contact to qualify comes from the triggering event's own payload, "
            f"not from static configuration."
        )


def _extract_contact_id(payload: ActionPayload) -> uuid.UUID:
    """Mirrors `product/automation/actions.py::_execute_update_contact()`'s
    own "read the dynamic entity reference from payload, never config"
    convention -- duplicated here (not imported) because
    `product.automation.actions` is off-limits to this module."""
    raw = payload.get("contact_id")
    if not isinstance(raw, str):
        raise WorkflowActionExecutionError(
            f"{ACTION_NAME} requires a contact_id in the triggering event's own payload."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise WorkflowActionExecutionError(
            f"{ACTION_NAME} payload.contact_id is not a valid UUID."
        ) from exc


async def _invoke(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> Mapping[str, object]:
    # `AIProviderNotConfiguredError` here if no provider is set. Fetched
    # explicitly (not left to `invoke_product_ai_tool()`'s own
    # `provider_name="fake"` default) so the Data Authorization request
    # below names the *actual* configured production provider -- without
    # this, every call would silently ask Data Authorization to evaluate
    # eligibility for `"fake"` regardless of what
    # `production_tool_registry()` actually built the tool against, which
    # would make a tenant's own `allowed_providers` list meaningless.
    provider = get_production_llm_provider()
    registry = production_tool_registry()
    outcome = await invoke_product_ai_tool(
        ACTION_NAME,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        resource_type="crm.contact",
        resource_id=str(contact_id),
        payload={"contact_id": str(contact_id)},
        provider_name=provider.name,
        registry=registry,
    )
    return outcome.output


def _execute(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    config: ActionConfig,
    payload: ActionPayload,
) -> ActionResult:
    contact_id = _extract_contact_id(payload)
    try:
        output = asyncio.run(_invoke(actor_user_id, tenant_id, contact_id))
    except (
        UnauthorizedToolInvocationError,
        TierRequiresApprovalError,
        DataAuthorizationRequiredError,
    ) as exc:
        raise WorkflowActionDeniedError(str(exc)) from exc
    except (TenantClosedError, TenantNotFoundError) as exc:
        # `control_plane.orchestration.service._execute_tool()`'s own
        # tenant-lifecycle fence (`core.tenancy.require_open_tenant()`) --
        # existing SaaS-OS enforcement, reused unchanged, never
        # duplicated here. A closed/suspended/deleted/purging/purged or
        # nonexistent tenant is a permanent condition this action can
        # never work around by retrying, so it lands in the same denial
        # bucket as an authorization failure -- never Automation's own
        # decision, only this adapter's classification of SaaS-OS's.
        raise WorkflowActionDeniedError(str(exc)) from exc
    except AIProviderNotConfiguredError as exc:
        raise WorkflowActionExecutionError(str(exc)) from exc
    except (ToolNotFoundError, ToolExecutionError) as exc:
        raise WorkflowActionExecutionError(str(exc)) from exc
    except AIValidationError as exc:
        # production_tool_registry()'s own defensive "declared capability
        # has no registered builder" check -- a deployment-configuration
        # error, not this workflow's fault, but not this workflow's to
        # fix either; treated the same as any other execution-time
        # provider/config failure this adapter cannot resolve itself.
        raise WorkflowActionExecutionError(str(exc)) from exc
    return {
        "contact_id": output.get("contact_id", str(contact_id)),
        "qualification": output.get("qualification", ""),
        "provider": output.get("provider", ""),
    }


def build_qualify_lead_workflow_action() -> WorkflowActionSpec:
    """The one adapter Phase 10.4A registers -- a `WorkflowActionSpec`
    wrapping this module's own `_validate_config`/`_execute`, matching
    `product/automation/actions.py`'s own established shape exactly (see
    that module's "per-action config validation"/"registry" sections)."""
    return WorkflowActionSpec(name=ACTION_NAME, validate_config=_validate_config, execute=_execute)


__all__ = ["ACTION_NAME", "build_qualify_lead_workflow_action"]
