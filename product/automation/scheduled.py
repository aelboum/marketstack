"""The "scheduled" trigger type's own sweep (docs/ROADMAP.md Phase 10.2's
own trigger list includes "scheduled time").

**No native scheduled/deferred job support exists to build a real
cron-style sweep on** -- the identical, already-disclosed SaaS-OS
capability gap `product/appointments/reminders.py`'s own module
docstring documents (`infra.jobs.enqueue_job()` exposes no deferred-
execution parameter; no sanctioned tenant-enumeration primitive exists
for a cron-style sweep across all tenants), applied here for the
identical reason. `docs/ADR/0007-automation-execution-substrate.md`'s
own "new gap" finding (no sync-to-async bridge into `infra.jobs`) applies
equally.

**Resulting, honest design**: `sweep_scheduled_workflows()` is a real,
correct, **per-tenant, on-demand** sweep -- not a global cron loop
pretending to be one, mirroring `reminders.py::send_due_reminders()`'s
identical shape and identical operational caveat (an external scheduler
must call the equivalent route once per tenant on a fixed interval; this
module fakes neither the schedule nor the trigger).

**"Due" is computed from `WorkflowRun` history, not a persisted
`next_run_at` column** -- a scheduled workflow's own `trigger_config`
declares `interval_hours` (an integer); this sweep finds the workflow's
own most recent `WorkflowRun` (any status) and fires again only if none
exists yet or the interval has elapsed since the last one's
`created_at`. This avoids a second, redundant "when do I run next" state
column that could drift from the run history itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from infra.db import select, tenant_session_scope

from product.automation.dispatcher import _run_workflow
from product.automation.models import STATUS_ACTIVE, Workflow, WorkflowRun
from product.automation.permissions import WORKFLOW_RESOURCE, require
from product.automation.workflows import SCHEDULED_TRIGGER_TYPE
from product.foundation.events import Event

DEFAULT_INTERVAL_HOURS = 24
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 24 * 30  # one month -- an explicit upper bound, never "unbounded"


@dataclass(frozen=True, slots=True)
class ScheduledSweepResult:
    swept_count: int
    fired_workflow_ids: list[uuid.UUID] = field(default_factory=list)


def _interval_hours(workflow: Workflow) -> int:
    raw = workflow.trigger_config.get("interval_hours", DEFAULT_INTERVAL_HOURS)
    if not isinstance(raw, int) or isinstance(raw, bool):
        return DEFAULT_INTERVAL_HOURS
    return max(MIN_INTERVAL_HOURS, min(raw, MAX_INTERVAL_HOURS))


def _is_due(session, tenant_id: uuid.UUID, workflow: Workflow, now: datetime) -> bool:
    last_run = session.execute(
        select(WorkflowRun.created_at)
        .where(WorkflowRun.tenant_id == tenant_id, WorkflowRun.workflow_id == workflow.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_run is None:
        return True
    return (now - last_run).total_seconds() >= _interval_hours(workflow) * 3600


def sweep_scheduled_workflows(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, now: datetime | None = None
) -> ScheduledSweepResult:
    """Fire every due `trigger_type="scheduled"` active workflow in
    `tenant_id`. `now` defaults to the real current UTC instant; the
    parameter exists only so tests can pin the sweep window
    deterministically (mirrors `reminders.py::send_due_reminders()`'s
    identical `now` parameter). Requires `(WORKFLOW_RESOURCE, "read")` --
    a real permission check, not merely a maintenance-task assumption; an
    unauthorized caller cannot use this to discover which scheduled
    workflows a tenant has configured."""
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="read")
    current = now if now is not None else datetime.now(UTC)

    with tenant_session_scope(tenant_id) as session:
        candidates = (
            session.execute(
                select(Workflow).where(
                    Workflow.tenant_id == tenant_id,
                    Workflow.trigger_type == SCHEDULED_TRIGGER_TYPE,
                    Workflow.status == STATUS_ACTIVE,
                )
            )
            .scalars()
            .all()
        )
        due = [w for w in candidates if _is_due(session, tenant_id, w, current)]
        for row in due:
            session.expunge(row)

    fired_ids: list[uuid.UUID] = []
    for workflow in due:
        event = Event(
            type=SCHEDULED_TRIGGER_TYPE,
            version=1,
            tenant_id=str(tenant_id),
            payload={},
            occurred_at=current,
        )
        dedup_key = f"scheduled:{current.isoformat()}"[:255]
        _run_workflow(workflow, event, dedup_key)
        fired_ids.append(workflow.id)

    return ScheduledSweepResult(swept_count=len(fired_ids), fired_workflow_ids=fired_ids)


__all__ = [
    "DEFAULT_INTERVAL_HOURS",
    "MAX_INTERVAL_HOURS",
    "MIN_INTERVAL_HOURS",
    "ScheduledSweepResult",
    "sweep_scheduled_workflows",
]
