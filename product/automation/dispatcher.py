"""The trigger dispatcher (docs/ROADMAP.md Phase 10.2). Subscribes to
every event-driven trigger type at module import time
(`product.foundation.events.subscribe()`), and, on each matching event,
looks up active workflows, evaluates conditions, and executes the
matching action -- all **synchronously, in the same call as the
triggering `publish()`** (`docs/ADR/0007-automation-execution-substrate.md`'s
own decision and reasoning for why this phase does not use
`infra.jobs`).

**Recursion guard** -- a workflow's own action can itself publish a
second event (`move_opportunity` calls `product.crm.opportunities
.change_stage()`, which itself publishes `crm.opportunity.stage_changed`
again). Because `publish()` calls every subscribed handler synchronously,
in the same call stack, that second `publish()` would otherwise re-enter
`_handle_event()` *while still inside* the first one -- an unbounded,
self-triggering chain (this phase's own explicit "do not permit
recursive/self-triggering workflows" / "runaway loops" requirement).
`_AUTOMATION_DEPTH` (a `contextvars.ContextVar`, safe across concurrent
requests/threads, unlike a bare module-level flag) is checked at the top
of `_handle_event()`: at depth >= `MAX_AUTOMATION_DEPTH` (1), the event is
recorded as `skipped` (audited, not silently dropped) and no workflow
runs. This is a hard, structural bound -- automations in this phase never
chain-trigger other automations, at all, not "chain up to some depth and
then stop": depth 1 means a workflow's own action-triggered event never
fires a second workflow, full stop.

**Idempotency** -- `product/automation/models.py::WorkflowRun`'s own
`UniqueConstraint(tenant_id, workflow_id, trigger_dedup_key)` is the real
guard; `_dedup_key()` derives a key from the event's own `occurred_at`
(microsecond-resolution) plus whichever well-known resource id the event
type carries, so the *same* trigger occurrence for the *same* workflow
can never execute twice, even if a caller-side bug or future async layer
somehow re-delivers the underlying event.

**Tenant identity is never trusted from the event payload** -- every
lookup below is scoped to `event.tenant_id` (the *publisher's* own,
already-real tenant context at the moment of the original mutation),
never a tenant id read out of `event.payload` itself (this phase's own
explicit "never trust tenant identity from event payloads" requirement).
"""

from __future__ import annotations

import contextvars
import uuid
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.automation.actions import execute_action
from product.automation.conditions import evaluate_conditions
from product.automation.models import (
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_SKIPPED,
    RUN_STATUS_SUCCESS,
    STATUS_ACTIVE,
    Workflow,
    WorkflowRun,
)
from product.foundation.events import Event, subscribe

MAX_AUTOMATION_DEPTH = 1

_AUTOMATION_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "automation_depth", default=0
)

# The event types this phase's trigger library actually wires up --
# see product/automation/__init__.py's own module docstring for the full
# trigger-catalog audit (which of the roadmap's own listed triggers this
# phase implements vs. defers).
TRIGGER_EVENT_TYPES = (
    "crm.opportunity.stage_changed",
    "crm.contact.created",
    "appointments.appointment.booked",
    "telephony.call.completed",
)

_TRIGGER_ID_FIELD_BY_EVENT_TYPE: dict[str, str] = {
    "crm.opportunity.stage_changed": "opportunity_id",
    "crm.contact.created": "contact_id",
    "appointments.appointment.booked": "appointment_id",
    "telephony.call.completed": "call_id",
}


def _dedup_key(event: Event) -> str:
    resource_field = _TRIGGER_ID_FIELD_BY_EVENT_TYPE.get(event.type)
    resource_id = event.payload.get(resource_field) if resource_field else None
    return f"{resource_id or 'na'}:{event.occurred_at.isoformat()}"[:255]


def _record_run(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    dedup_key: str,
    *,
    status: str,
    error: str | None = None,
) -> bool:
    """Returns `True` if this call actually recorded the run (first
    delivery for this dedup key), `False` if it was already recorded
    (duplicate -- caller must not re-execute the action). Uses a
    `SAVEPOINT` (`session.begin_nested()`), mirroring
    `product/telephony/calls.py::_record_event_idempotently()`'s
    identical reasoning -- this may run inside a transaction the caller
    already has open."""
    try:
        with tenant_session_scope(tenant_id) as session:
            with session.begin_nested():
                session.add(
                    WorkflowRun(
                        tenant_id=tenant_id,
                        workflow_id=workflow_id,
                        trigger_dedup_key=dedup_key,
                        status=status,
                        error=error,
                    )
                )
                session.flush()
        return True
    except IntegrityError:
        return False


def _matching_active_workflows(tenant_id: uuid.UUID, event_type: str) -> list[Workflow]:
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Workflow).where(
                    Workflow.tenant_id == tenant_id,
                    Workflow.trigger_type == event_type,
                    Workflow.status == STATUS_ACTIVE,
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return list(rows)


def _finalize_run(
    tenant_id: uuid.UUID, workflow_id: uuid.UUID, dedup_key: str, *, status: str, error: str | None
) -> None:
    with tenant_session_scope(tenant_id) as session:
        row = session.execute(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.trigger_dedup_key == dedup_key,
            )
        ).scalar_one()
        row.status = status
        row.error = error
        row.completed_at = datetime.now(UTC)


def _run_workflow(workflow: Workflow, event: Event, dedup_key: str) -> None:
    tenant_id = uuid.UUID(event.tenant_id)
    if not evaluate_conditions(workflow.conditions, event.payload):
        _record_run(tenant_id, workflow.id, dedup_key, status=RUN_STATUS_SKIPPED)
        return

    # Reserve the dedup key as PENDING *before* the action runs -- mirrors
    # core.idempotency's own begin/finalize two-step shape for an
    # operation with an external call in the middle (module docstring).
    # A row that never leaves PENDING (crash mid-action) is a genuine,
    # visible "did this actually run?" signal, never a false SUCCESS.
    recorded = _record_run(tenant_id, workflow.id, dedup_key, status=RUN_STATUS_PENDING)
    if not recorded:
        return  # already reserved/executed for this exact trigger occurrence

    token = _AUTOMATION_DEPTH.set(_AUTOMATION_DEPTH.get() + 1)
    try:
        result = execute_action(
            workflow.action_type,
            workflow.created_by_user_id,
            tenant_id,
            workflow.action_config,
            event.payload,
        )
        _finalize_run(tenant_id, workflow.id, dedup_key, status=RUN_STATUS_SUCCESS, error=None)
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=workflow.created_by_user_id,
            action="automation.workflow.execute",
            resource_type="automation.workflow",
            resource_id=str(workflow.id),
            outcome=AuditOutcome.SUCCESS,
            metadata={
                "trigger_type": event.type,
                "action_type": workflow.action_type,
                "result_keys": sorted(result.keys()),
            },
        )
    except Exception as exc:
        # A workflow's own action failure must never propagate back to
        # the original request that published the triggering event (an
        # unrelated tenant automation with a down webhook target must
        # never turn an ordinary "create contact" call into a 500) --
        # recorded as a failed WorkflowRun and a FAILURE audit entry,
        # never re-raised.
        error_text = f"{type(exc).__name__}: {exc}"[:2000]
        _finalize_run(tenant_id, workflow.id, dedup_key, status=RUN_STATUS_FAILED, error=error_text)
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=workflow.created_by_user_id,
            action="automation.workflow.execute",
            resource_type="automation.workflow",
            resource_id=str(workflow.id),
            outcome=AuditOutcome.FAILURE,
            metadata={"trigger_type": event.type, "action_type": workflow.action_type},
        )
    finally:
        _AUTOMATION_DEPTH.reset(token)


def _handle_event(event: Event) -> None:
    if _AUTOMATION_DEPTH.get() >= MAX_AUTOMATION_DEPTH:
        record(
            tenant_id=uuid.UUID(event.tenant_id),
            actor_type=ActorType.SYSTEM,
            action="automation.trigger.max_depth_exceeded",
            resource_type="automation.workflow",
            resource_id=event.type,
            outcome=AuditOutcome.DENIED,
            metadata={"trigger_type": event.type},
        )
        return

    tenant_id = uuid.UUID(event.tenant_id)
    dedup_key = _dedup_key(event)
    workflows = _matching_active_workflows(tenant_id, event.type)
    for workflow in workflows:
        try:
            _run_workflow(workflow, event, dedup_key)
        except Exception:  # noqa: BLE001 -- one workflow's failure must never abort the rest
            continue


# Subscribed at import time, module level -- mirrors every other
# module's own event_handlers.py convention exactly (e.g.
# product/telephony/event_handlers.py's own unconditional, module-level
# subscribe() call). Ordinary Python import caching means this module's
# top-level code runs at most once per process, so no extra
# idempotent-registration guard is needed here.
for _event_type in TRIGGER_EVENT_TYPES:
    subscribe(_event_type, _handle_event)

__all__ = ["MAX_AUTOMATION_DEPTH", "TRIGGER_EVENT_TYPES"]
