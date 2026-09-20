"""Thin Temporal client wrapper for the Phase 10.3 infrastructure spike
(package docstring: `product/automation/durable/__init__.py`).

**Privacy / history -- what this spike actually puts into Temporal.**
Determined by reading the SDK's own behavior directly, not assumed:
Temporal's server persists a workflow's *complete event history* --
every `WorkflowExecutionStarted` event's own input, every
`ActivityTaskScheduled`/`ActivityTaskCompleted` event's own input/result,
and any recorded failure -- as part of how it replays and recovers a
workflow at all (this is the mechanism this whole spike exists to prove,
not an incidental side effect). Concretely, for `submit_probe_workflow()`
below: the workflow's own input (`ProbeWorkflowInput` -- `tenant_id`,
`resource_id`), and each activity's own input/output (`ProbeActivityInput`/
`ProbeActivityOutput` -- the same two fields, echoed back, plus a
retry-attempt counter) are all written into Temporal's history, by the
default (unencrypted) `DataConverter`, for as long as that workflow
execution's history is retained (the server's own configured retention
period -- unset here, so whatever the `temporal` Docker Compose service's
own default is, documented in this phase's own ADR update). **This spike
therefore never passes a real tenant_id, a real resource id, or any other
real customer data as workflow/activity input -- every test and every
manual run in this spike uses synthetic identifiers only** (a literal
string like `"spike-tenant-1"` or a freshly generated UUID with no
corresponding real `core.tenants` row), so nothing this spike does writes
real customer data into Temporal's history. A future production
integration that passes real ids as workflow/activity input must either
accept that those ids (not the full row content -- `product.automation`'s
own activities pass ids, never payload content, mirroring
`product/automation/dispatcher.py`'s own "tenant identity is never
trusted from event payloads, and the dedup key carries only ids" pattern)
land in Temporal's history, or configure the SDK's own `DataConverter`
with a `PayloadCodec` (Temporal's documented encryption-at-rest hook for
workflow/activity payloads) -- **not implemented or guaranteed here**;
this spike does not invent an encryption guarantee it has not built.

**Tenant lifecycle / purge interface (proved, not fully integrated).**
The eventual `TenantPurgeParticipant` for durable workflows needs to (1)
identify every Temporal workflow execution belonging to a tenant being
purged, and (2) terminate/cancel them, with the *Product-side* purge
remaining authoritative (a stray, un-terminated Temporal execution can
never, by itself, re-authorize anything for a closed tenant -- `core.rbac
.can()` already fails for a `PURGING`/`PURGED` tenant regardless, per
`core/tenancy/lifecycle.py`'s own `PRINCIPAL_INACCESSIBLE_STATUSES`; this
is defense in depth, not the only safety net).

This spike implements and tests the **workflow-ID-prefix strategy**:
`_workflow_id_for_tenant()` embeds `tenant_id` as a deterministic prefix
of every workflow id this module starts
(`f"automation-durable-probe:{tenant_id}:{uuid4()}"`), and
`list_workflows_for_tenant()`/`terminate_workflows_for_tenant()` list
*every* execution via `client.list_workflows()` (Temporal's own
`ListWorkflowExecutions`, available on any server with no additional
configuration) and filter/act on the ones whose id starts with that
tenant's own prefix. This works unconditionally, on any Temporal
deployment, with zero server-side setup -- the tradeoff is that it lists
every execution in the namespace to find a tenant's own, which does not
scale to a namespace with a very large number of concurrent executions.
**Documented, not implemented here**: a production implementation should
instead register a custom Keyword search attribute (e.g. `TenantId`,
via `temporal operator search-attribute create --name TenantId --type
Keyword` once per namespace/deployment) and pass it via
`typed_search_attributes=` on `client.start_workflow()`, so
`list_workflows(query="TenantId = '...'")` filters server-side --
strictly better at scale, but it requires that one-time namespace
registration step this spike does not perform (adding it here would be
exactly the kind of speculative production purge code this phase's own
instructions say to leave out unless strictly required for the
infrastructure proof; the workflow-ID-prefix strategy alone is sufficient
to prove the interface boundary this phase asks for).
"""

from __future__ import annotations

import re
import uuid

from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle

from product.automation.durable.config import DurableConfig, get_durable_config
from product.automation.durable.workflows import (
    ProbeWorkflow,
    ProbeWorkflowInput,
    ProbeWorkflowResult,
)

_WORKFLOW_ID_PREFIX_TEMPLATE = "automation-durable-probe:{tenant_id}:"
# The exact shape `_workflow_id_for_tenant()` always generates: the
# prefix above, followed by exactly `uuid.uuid4().hex`'s own 32
# lowercase-hex characters, nothing else. Matched via a fully-anchored
# regex, never `str.startswith()`, for a real reason: a bare prefix
# check would let a maliciously/accidentally crafted `tenant_id`
# containing its own `:` (e.g. `"a:evil"`) produce a workflow id
# (`"automation-durable-probe:a:evil:<hex>"`) that `str.startswith(
# "automation-durable-probe:a:")` would wrongly also match for tenant
# `"a"` -- a real tenant-identity-confusion bug in the purge-interface
# boundary this module exists to prove out, caught and fixed during this
# spike's own security review, not merely theoretical. The fixed-length
# hex-only suffix, anchored at both ends, makes that collision
# impossible regardless of what characters a `tenant_id` contains.
_WORKFLOW_ID_HEX_SUFFIX_LENGTH = 32


def _workflow_id_for_tenant(tenant_id: str) -> str:
    return f"{_WORKFLOW_ID_PREFIX_TEMPLATE.format(tenant_id=tenant_id)}{uuid.uuid4().hex}"


def _workflow_id_pattern_for_tenant(tenant_id: str) -> re.Pattern[str]:
    prefix = _WORKFLOW_ID_PREFIX_TEMPLATE.format(tenant_id=tenant_id)
    return re.compile(rf"^{re.escape(prefix)}[0-9a-f]{{{_WORKFLOW_ID_HEX_SUFFIX_LENGTH}}}$")


async def get_client(config: DurableConfig | None = None) -> Client:
    """A connected Temporal client. Raises `DurableConfigurationError`
    (via `get_durable_config()`) if `TEMPORAL_ADDRESS` is unset -- never
    silently connects to a default endpoint (`config.py`'s own
    docstring)."""
    cfg = config or get_durable_config()
    return await Client.connect(cfg.target_host, namespace=cfg.namespace)


async def submit_probe_workflow(
    client: Client, *, tenant_id: str, resource_id: str, task_queue: str
) -> WorkflowHandle:
    """Starts one `ProbeWorkflow` execution, id-tagged with `tenant_id`
    per this module's own tenant-lifecycle/purge-interface strategy
    (module docstring). Returns the handle (never blocks for
    completion -- `await handle.result()` is the caller's own, separate
    choice)."""
    return await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(tenant_id=tenant_id, resource_id=resource_id),
        id=_workflow_id_for_tenant(tenant_id),
        task_queue=task_queue,
    )


async def list_workflows_for_tenant(client: Client, *, tenant_id: str) -> list[WorkflowHandle]:
    """Every workflow execution (any status) whose id was minted by
    `submit_probe_workflow()` for this exact `tenant_id` -- module
    docstring's "workflow-ID-prefix strategy," matched via
    `_workflow_id_pattern_for_tenant()`'s fully-anchored pattern (never a
    bare prefix check -- see that function's own docstring for why).
    Lists every execution in the namespace and filters client-side; see
    module docstring for why, and for the server-side alternative a
    production integration should use instead."""
    pattern = _workflow_id_pattern_for_tenant(tenant_id)
    matches: list[WorkflowHandle] = []
    async for execution in client.list_workflows():
        if pattern.match(execution.id):
            matches.append(client.get_workflow_handle(execution.id, run_id=execution.run_id))
    return matches


async def terminate_workflows_for_tenant(client: Client, *, tenant_id: str, reason: str) -> int:
    """Terminates every currently-running workflow execution belonging to
    `tenant_id` (module docstring). Returns the count actually
    terminated (a completed/already-terminated execution is skipped, not
    an error -- mirrors `TenantPurgeParticipant.purge_tenant_data()`'s
    own "deleting rows that are already gone must be a silent no-op"
    contract, `core/tenancy/purge_participants.py`, even though this
    spike does not register as a real purge participant). Product-side
    purge remains authoritative regardless of this call's outcome --
    module docstring."""
    handles = await list_workflows_for_tenant(client, tenant_id=tenant_id)
    terminated = 0
    for handle in handles:
        description = await handle.describe()
        if description.status != WorkflowExecutionStatus.RUNNING:
            continue
        await handle.terminate(reason=reason)
        terminated += 1
    return terminated


__all__ = [
    "get_client",
    "submit_probe_workflow",
    "list_workflows_for_tenant",
    "terminate_workflows_for_tenant",
    "ProbeWorkflow",
    "ProbeWorkflowInput",
    "ProbeWorkflowResult",
]
