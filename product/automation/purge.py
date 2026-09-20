"""Tenant purge participant for the `automation` schema -- extended in
Phase 10.3 to also purge the production durable-workflow tables
(`product/automation/durable/models.py`) and to terminate any of the
tenant's own still-active Temporal executions first (docs/ROADMAP.md
Phase 10.3's own "Tenant purge" requirement). 10.2's own single-step
tables (`Workflow`, `WorkflowRun`) are unaffected -- same participant,
same registration, same `name` (`"automation.*"`), extended, never
replaced. Registered from `product/api/main.py::create_app()`.

**Product-side purge remains authoritative; Temporal termination is a
best-effort courtesy, not a precondition this function trusts blindly to
protect tenant data.** `core.rbac.can()` already denies every
authorization-gated call for a `SUSPENDED`/`DELETED`/`PURGING`/`PURGED`
tenant regardless of whether a stray Temporal execution is still running
(`core/tenancy/lifecycle.py::PRINCIPAL_INACCESSIBLE_STATUSES`, verified
during the Phase 10.3 infrastructure spike's own review) -- that
structural guarantee is unconditional and does not depend on this
module ever running at all. What this module adds is defense in depth
*and* hygiene: a terminated execution stops consuming Temporal resources
and stops accumulating further history for a tenant whose data is being
erased, rather than merely being harmlessly unable to do anything.

**`asyncio.run()` is used here, deliberately, unlike anywhere in the
*sync* event-publisher call chain 10.2's own `product/automation
/dispatcher.py` and this phase's own `product/automation/durable
/triggers.py` are careful to avoid it.** The reason this is safe here and
not there: `purge_tenant_data()` is called by `core.tenancy.purge_tenant()`,
itself only ever invoked from trusted, synchronous ops/admin tooling
(`core/tenancy/purge_participants.py`'s own module docstring; every
other module-owned purge step in this codebase is a plain synchronous
function for the identical reason) -- never from inside an already-running
asyncio event loop the way a Product event publisher can be
(`docs/ADR/0007-automation-execution-substrate.md`'s own Phase 10.1
finding). A caller that changes this in the future would need to revisit
this reasoning, not merely this file.

**Fails closed.** If the tenant has any non-terminal durable run
(`temporal_workflow_id` set, status not yet terminal) and Temporal
itself cannot be reached, this function raises rather than silently
skipping the termination step -- `core.tenancy.purge_tenant()`'s own
contract (`core/tenancy/purge_participants.py`'s own module docstring)
classifies that as a bounded `"participant_error"` and does *not*
transition the tenant to `PURGED`, exactly the fail-closed behavior a
tenant erasure step must have. A tenant that never used durable
workflows at all incurs no Temporal dependency during its own purge --
`get_client()` is never called if there is nothing to terminate.
"""

from __future__ import annotations

import asyncio
import uuid

from core.audit_log import ActorType, AuditOutcome, record
from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.automation.durable.client import get_client
from product.automation.durable.models import TERMINAL_RUN_STATUSES
from product.automation.durable.models import Run as DurableRun
from product.automation.durable.models import RunStep as DurableRunStep
from product.automation.durable.models import Workflow as DurableWorkflow
from product.automation.durable.models import WorkflowVersion as DurableWorkflowVersion
from product.automation.models import Workflow, WorkflowRun

_PURGE_ORDER = (
    WorkflowRun,
    Workflow,
    DurableRunStep,
    DurableRun,
    DurableWorkflowVersion,
    DurableWorkflow,
)


async def _terminate_active_durable_executions(
    tenant_id: uuid.UUID, temporal_workflow_ids: list[str]
) -> None:
    client = await get_client()
    for temporal_workflow_id in temporal_workflow_ids:
        handle = client.get_workflow_handle(temporal_workflow_id)
        await handle.terminate(reason=f"tenant {tenant_id} purged")


class AutomationDataPurgeParticipant:
    @property
    def name(self) -> str:
        return "automation.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            active_temporal_ids = (
                session.execute(
                    select(DurableRun.temporal_workflow_id).where(
                        DurableRun.tenant_id == tenant_id,
                        DurableRun.status.not_in(TERMINAL_RUN_STATUSES),
                        DurableRun.temporal_workflow_id.is_not(None),
                    )
                )
                .scalars()
                .all()
            )

        temporal_ids = [w for w in active_temporal_ids if w is not None]
        if temporal_ids:
            # Fails closed (module docstring): a connection failure here
            # propagates unchanged, which is what makes
            # core.tenancy.purge_tenant() classify this as a
            # participant_error and refuse to mark the tenant PURGED.
            asyncio.run(_terminate_active_durable_executions(tenant_id, temporal_ids))
            record(
                tenant_id=tenant_id,
                actor_type=ActorType.SYSTEM,
                action="automation.durable_run.purge_terminated",
                resource_type="automation.durable_run",
                resource_id=str(tenant_id),
                outcome=AuditOutcome.SUCCESS,
                metadata={"terminated_count": len(temporal_ids)},
            )

        with tenant_session_scope(tenant_id) as session:
            for model in _PURGE_ORDER:
                rows = (
                    session.execute(
                        select(model).where(model.tenant_id == tenant_id).with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    session.delete(row)
                session.flush()


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    active_registry = registry if registry is not None else default_registry()
    participant = AutomationDataPurgeParticipant()
    try:
        active_registry.register(participant)
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, type(participant)) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise
