"""Event-triggered durable runs (docs/ROADMAP.md Phase 10.3). Reuses the
existing Product event model unchanged -- `product.foundation.events
.subscribe()` -- via a narrow, additive adapter, never a redesign of
`product/automation/dispatcher.py`'s own 10.2 trigger handling (which
this module does not import, call, or modify in any way; 10.2's own
single-step behavior is completely unaffected by this file existing).

**The same sync/async boundary `docs/ADR/0007-automation-execution-substrate.md`'s
own Phase 10.1 spike disclosed is still real, and adopting Temporal does
not remove it.** `product.foundation.events.subscribe()` handlers are
synchronous, called in the same call stack as the original, itself
synchronous, event publisher (`product.crm.contacts.create_contact()`,
etc.) -- but starting a Temporal workflow execution
(`temporalio.client.Client.start_workflow()`) is `async def`-only. This
module's own trigger handler therefore does the only thing a synchronous
handler can safely do without an `asyncio.run()` bridge that risks
running inside an already-active event loop (the exact hazard ADR-0007
identified and this phase's own instructions do not ask to be solved):
it performs a **bounded, synchronous, Postgres-only** write -- reserving
a `Run` row in `RUN_STATUS_QUEUED` (`product/automation/durable/runs.py
::_reserve_run()`, reused unchanged) -- and nothing else. It never calls
Temporal directly.

**Actually starting a queued run on Temporal is a separate, explicit,
narrow step -- `submit_queued_durable_runs()`.** This mirrors
`product/automation/scheduled.py`'s own precedent exactly (that module's
own docstring: "never called by this product's own code; exists for
manual/testing invocation or an external per-tenant scheduler") -- the
same disclosed scheduling-primitive gap 10.2 already has
(`core.tenancy.service` has no tenant-enumeration primitive for a
cron-style sweep), not a new one, and not something Temporal's own
adoption changes: Temporal solves *durable execution*, not *how a
synchronous Python call site reaches an async client*. This is a bounded
limitation, documented rather than worked around with a second scheduler
or an unsafe bridge (this phase's own explicit instructions: "document
it as a bounded limitation rather than creating a second scheduler").
"""

from __future__ import annotations

import uuid

from infra.db import select, tenant_session_scope

from product.automation.dispatcher import TRIGGER_EVENT_TYPES
from product.automation.durable.models import (
    RUN_STATUS_QUEUED,
    STATUS_ACTIVE,
    VERSION_STATUS_PUBLISHED,
    Run,
    Workflow,
    WorkflowVersion,
)
from product.automation.durable.permissions import DURABLE_WORKFLOW_RESOURCE, require
from product.automation.durable.runs import (
    RunView,
    _reserve_run,
    _run_to_view,
    _submit_run_to_temporal,
)
from product.foundation.events import Event, subscribe


def _dedup_key(workflow_version_id: uuid.UUID, event: Event) -> str:
    """Mirrors `product/automation/dispatcher.py::_dedup_key()`'s own
    microsecond-resolution-occurred_at approach, additionally scoped by
    `workflow_version_id` (a durable workflow can be re-published to a
    new version between event deliveries; each version's own queued runs
    must dedup independently)."""
    return f"{workflow_version_id.hex}:{event.occurred_at.isoformat()}"[:255]


def _handle_trigger_event(event: Event) -> None:
    tenant_id = uuid.UUID(event.tenant_id)
    # Every value this handler needs (workflow id, published version id,
    # and the workflow's own creator -- the execution identity for an
    # event-triggered run, identical privilege-boundary discipline to
    # 10.2's own `Workflow.created_by_user_id`,
    # `product/automation/durable/definitions.py`'s own module docstring)
    # is read inside this one session block, so nothing below reaches
    # for a detached/out-of-scope ORM attribute.
    with tenant_session_scope(tenant_id) as session:
        matching_workflows = (
            session.execute(
                select(Workflow).where(
                    Workflow.tenant_id == tenant_id, Workflow.status == STATUS_ACTIVE
                )
            )
            .scalars()
            .all()
        )
        candidates: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
        for workflow_row in matching_workflows:
            if workflow_row.current_published_version_id is None:
                continue
            version_row = session.get(WorkflowVersion, workflow_row.current_published_version_id)
            if (
                version_row is not None
                and version_row.status == VERSION_STATUS_PUBLISHED
                and version_row.trigger_type == event.type
            ):
                candidates.append(
                    (workflow_row.id, version_row.id, workflow_row.created_by_user_id)
                )

    for workflow_id, workflow_version_id, actor_user_id in candidates:
        dedup_key = _dedup_key(workflow_version_id, event)
        _reserve_run(
            tenant_id,
            workflow_id,
            workflow_version_id,
            actor_user_id,
            dedup_key,
            dict(event.payload),
        )


# Subscribed at import time, module level -- mirrors every other
# module's own event_handlers.py convention (module docstring), and
# 10.2's own product/automation/dispatcher.py precedent exactly. Reuses
# the identical event-type catalog (never a separately invented set).
for _event_type in TRIGGER_EVENT_TYPES:
    subscribe(_event_type, _handle_trigger_event)


async def submit_queued_durable_runs(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    """Explicitly-invoked sweep (module docstring) -- submits every
    `RUN_STATUS_QUEUED` run for `tenant_id` to Temporal. Returns the
    count actually submitted. Authorization mirrors
    `product/automation/scheduled.py::sweep_scheduled_workflows()`'s own
    "read" bar exactly -- this observes and advances existing queued
    runs, it does not create a new business object."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        queued = (
            session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.status == RUN_STATUS_QUEUED)
            )
            .scalars()
            .all()
        )
        run_ids_and_versions = []
        for run_row in queued:
            version_row = session.get(WorkflowVersion, run_row.workflow_version_id)
            assert version_row is not None
            session.expunge(run_row)
            session.expunge(version_row)
            run_ids_and_versions.append((run_row, version_row))

    submitted = 0
    for run_row, version_row in run_ids_and_versions:
        await _submit_run_to_temporal(tenant_id, run_row, version_row)
        submitted += 1
    return submitted


def list_queued_runs_for_tenant(tenant_id: uuid.UUID) -> list[RunView]:
    """Read-only helper for tests/observability -- not authorization-gated
    on its own (callers are expected to be trusted internal code or
    already-authorized callers of `submit_queued_durable_runs()`)."""
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.status == RUN_STATUS_QUEUED)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_run_to_view(row) for row in rows]


__all__ = ["list_queued_runs_for_tenant", "submit_queued_durable_runs"]
