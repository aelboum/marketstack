"""Temporal activities that form the adapter between durable workflow
code and existing Product business logic (docs/ROADMAP.md Phase 10.3).

    Temporal workflow (production_workflow.py)
        |
        v
    Temporal activity (this module)
        |
        v
    product.automation.actions.execute_action()   (unchanged, 10.2's own)
        |
        v
    existing domain/service layer (product.crm.*, core.email, ...)
        |
        v
    SaaS-OS/Core authorization (core.rbac.can()) + audit (core.audit_log)
                                                   + DB (infra.db)

**No business logic lives in workflow code -- all of it lives here, or
one layer further down in `product.automation.actions`, unchanged.**
This module's own activities are the *only* place `product/automation/
durable/production_workflow.py` reaches outside pure, deterministic
Python.

**Every activity here is a plain, synchronous `def`, not `async def`.**
Each one performs real, blocking Postgres I/O
(`infra.db.tenant_session_scope`) and, for `execute_step_action_activity`,
calls straight into `product.automation.actions.execute_action()` --
itself entirely synchronous. Running a blocking sync function as a
Temporal activity requires the Worker to dispatch it through a thread
pool (`activity_executor=`, `worker.py`'s own module docstring) rather
than on the asyncio event loop the Worker's own poll/dispatch machinery
runs on -- the SDK-documented pattern for wrapping exactly this kind of
call, not a workaround.

**Execution-time authorization is not this module's own decision --
it is `product.automation.actions.execute_action()`'s, unchanged.**
`execute_step_action_activity()` passes the run's own `actor_user_id`
straight through to `execute_action()`, which calls straight into the
underlying CRM/email/webhook function's own `require()`/`core.rbac
.can()` check, evaluated fresh, every single invocation (including a
Temporal-replayed retry) -- `core.rbac.can()` is proven live and
uncached (`core/rbac/authorization.py`'s own docstring, verified during
the Phase 10.3 infrastructure spike's own review). No permission
decision is ever made here, cached here, or skipped here.

**Business idempotency, not "Temporal will only execute this once."**
Temporal activities are at-least-once; a worker crash after
`execute_action()`'s own side effect but before this activity returns
would otherwise cause Temporal to retry the *entire* activity, including
the side effect. `execute_step_action_activity()` wraps the call in
`core.idempotency.begin_idempotent_operation()`/
`finalize_idempotent_operation()` -- the same two-step primitive
`core/idempotency/service.py` documents for "an operation with an
external call in the middle," keyed by `f"{run_id}.{step_key}"`
(deterministic, unique per step-execution-slot, safe under
`core.idempotency`'s own key charset) -- so a retried invocation for the
exact same run+step replays the already-recorded result instead of
re-running the real side effect a second time.

**Failure classification -- retryable vs. not.** An authorization
denial, a malformed action config, or an unknown reference are permanent
outcomes an infinite Temporal retry would never fix; each is caught here
and re-raised as `temporalio.exceptions.ApplicationError(...,
non_retryable=True)`, which stops Temporal's own retry policy
immediately (`production_workflow.py`'s own bounded `RetryPolicy` for
the *transient*-failure case this leaves alone). An authorization denial
is additionally audited as its own event
(`automation.durable_run.authorization_denied`) -- this phase's own
required audit event. Both classification lists below are closed and
explicit, and both include the *domain-layer* error types
(`product.crm.errors.*`) that `execute_action()` deliberately passes
through unnormalized -- see the comment on `_PERMANENT_DENIAL_ERRORS`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import (
    IdempotencyStatus,
    begin_idempotent_operation,
    finalize_idempotent_operation,
)
from infra.db import select, tenant_session_scope
from temporalio import activity
from temporalio.exceptions import ApplicationError

from product.automation.actions import execute_action
from product.automation.durable.dsl import STEP_TYPE_WAIT_FOR_EVENT
from product.automation.durable.models import (
    MAX_ERROR_LENGTH,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_WAITING,
    STEP_RUN_STATUS_RUNNING,
    Run,
    RunStep,
)
from product.automation.errors import (
    AutomationAccessDeniedError,
    AutomationActionError,
    AutomationConditionError,
    AutomationReferenceNotFoundError,
    AutomationValidationError,
)
from product.crm.errors import (
    CrmAccessDeniedError,
    CrmReferenceNotFoundError,
    CrmValidationError,
)
from product.foundation.workflow_actions import (
    UnknownWorkflowActionError,
    WorkflowActionConfigError,
    WorkflowActionDeniedError,
)

# `execute_action()` deliberately does NOT normalize the underlying
# domain call's own exceptions (`product/automation/actions.py`: only
# `send_email`/`send_webhook`'s provider errors are wrapped, because only
# those have a provider boundary to normalize at). A CRM action's own
# `CrmAccessDeniedError`/`CrmReferenceNotFoundError`/`CrmValidationError`
# therefore reaches this activity *raw*, and classifying only the
# `Automation*` wrappers would leave exactly the permanent failures this
# phase must never retry -- an execution-time authorization denial above
# all -- falling through to the generic retryable branch. The list is
# closed and explicit, matching this phase's own bounded action
# vocabulary: `create_task`/`update_contact`/`move_opportunity` reach
# `product.crm`, and `send_email`/`send_webhook` are already normalized
# to `AutomationActionError`/`AutomationValidationError` by
# `execute_action()` itself.
# Phase 10.3A adds the three domain-neutral types from
# `product/foundation/workflow_actions.py` alongside the domain-specific
# ones. An action implementation owned by another product domain cannot
# import `product.automation.errors` (the import-linter contracts forbid
# it), so the neutral types are the vocabulary it signals permanence
# with -- classified here identically to their Automation/CRM
# counterparts, so a foreign action gets exactly the same retry
# treatment as a built-in one. `WorkflowActionExecutionError` is
# deliberately absent from both lists: like `AutomationActionError`, it
# is the *potentially transient* case the bounded RetryPolicy handles.
_PERMANENT_DENIAL_ERRORS: tuple[type[Exception], ...] = (
    AutomationAccessDeniedError,
    CrmAccessDeniedError,
    WorkflowActionDeniedError,
)

_NON_RETRYABLE_ACTION_ERRORS: tuple[type[Exception], ...] = (
    AutomationValidationError,
    AutomationConditionError,
    AutomationReferenceNotFoundError,
    CrmReferenceNotFoundError,
    CrmValidationError,
    WorkflowActionConfigError,
    UnknownWorkflowActionError,
)


def _truncate(text: str | None) -> str | None:
    return text[:MAX_ERROR_LENGTH] if text is not None else None


# --- Business-action execution (idempotent, re-authorizing) ----------------


@dataclass(frozen=True, slots=True)
class ExecuteStepActionInput:
    tenant_id: str
    run_id: str
    step_key: str
    actor_user_id: str
    action_type: str
    action_config: dict
    context: dict


@dataclass(frozen=True, slots=True)
class ExecuteStepActionOutput:
    result: dict = field(default_factory=dict)


@activity.defn
def execute_step_action_activity(input: ExecuteStepActionInput) -> ExecuteStepActionOutput:
    tenant_id = uuid.UUID(input.tenant_id)
    idempotency_key = f"{input.run_id}.{input.step_key}"
    reservation = begin_idempotent_operation(
        tenant_id,
        operation="automation.durable_run.step",
        idempotency_key=idempotency_key,
        fingerprint_payload={
            "action_type": input.action_type,
            "action_config": input.action_config,
        },
    )
    if reservation.is_replay:
        return ExecuteStepActionOutput(result=reservation.result or {})

    try:
        result = execute_action(
            input.action_type,
            uuid.UUID(input.actor_user_id),
            tenant_id,
            input.action_config,
            input.context,
        )
    except _PERMANENT_DENIAL_ERRORS as exc:
        finalize_idempotent_operation(
            tenant_id, reservation.record_id, status=IdempotencyStatus.FAILED
        )
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=uuid.UUID(input.actor_user_id),
            action="automation.durable_run.authorization_denied",
            resource_type="automation.durable_run",
            resource_id=input.run_id,
            outcome=AuditOutcome.DENIED,
            metadata={"step_key": input.step_key, "action_type": input.action_type},
        )
        raise ApplicationError(str(exc), non_retryable=True) from exc
    except _NON_RETRYABLE_ACTION_ERRORS as exc:
        finalize_idempotent_operation(
            tenant_id, reservation.record_id, status=IdempotencyStatus.FAILED
        )
        raise ApplicationError(str(exc), non_retryable=True) from exc
    except Exception as exc:
        finalize_idempotent_operation(
            tenant_id, reservation.record_id, status=IdempotencyStatus.FAILED
        )
        raise AutomationActionError(f"{type(exc).__name__}: {exc}") from exc

    finalize_idempotent_operation(
        tenant_id, reservation.record_id, status=IdempotencyStatus.SUCCEEDED, result=result
    )
    return ExecuteStepActionOutput(result=result)


# --- Run/step lifecycle (business state + audit, never Temporal history) --


@dataclass(frozen=True, slots=True)
class StartRunInput:
    tenant_id: str
    run_id: str


@activity.defn
def start_run_activity(input: StartRunInput) -> None:
    tenant_id = uuid.UUID(input.tenant_id)
    run_id = uuid.UUID(input.run_id)
    with tenant_session_scope(tenant_id) as session:
        run = session.get(Run, run_id)
        assert run is not None  # the service layer only ever schedules a real run row
        run.status = RUN_STATUS_RUNNING
        run.started_at = datetime.now(UTC)
        actor_user_id = run.actor_user_id
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_run.started",
        resource_type="automation.durable_run",
        resource_id=input.run_id,
        outcome=AuditOutcome.SUCCESS,
    )


@dataclass(frozen=True, slots=True)
class StepStartedInput:
    tenant_id: str
    run_id: str
    step_key: str
    step_type: str
    waiting_for_event_type: str | None = None


@activity.defn
def record_step_started_activity(input: StepStartedInput) -> None:
    tenant_id = uuid.UUID(input.tenant_id)
    run_id = uuid.UUID(input.run_id)
    with tenant_session_scope(tenant_id) as session:
        session.add(
            RunStep(
                tenant_id=tenant_id,
                run_id=run_id,
                step_key=input.step_key,
                step_type=input.step_type,
                status=STEP_RUN_STATUS_RUNNING,
            )
        )
        run = session.get(Run, run_id)
        assert run is not None
        run.current_step_key = input.step_key
        is_waiting = input.step_type == STEP_TYPE_WAIT_FOR_EVENT
        run.status = RUN_STATUS_WAITING if is_waiting else RUN_STATUS_RUNNING
        run.waiting_for_event_type = input.waiting_for_event_type if is_waiting else None
        actor_user_id = run.actor_user_id
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_run.step_started",
        resource_type="automation.durable_run",
        resource_id=input.run_id,
        outcome=AuditOutcome.SUCCESS,
        metadata={"step_key": input.step_key, "step_type": input.step_type},
    )


@dataclass(frozen=True, slots=True)
class StepFinishedInput:
    tenant_id: str
    run_id: str
    step_key: str
    status: str
    error: str | None = None
    context_update: dict = field(default_factory=dict)


@activity.defn
def record_step_finished_activity(input: StepFinishedInput) -> None:
    tenant_id = uuid.UUID(input.tenant_id)
    run_id = uuid.UUID(input.run_id)
    with tenant_session_scope(tenant_id) as session:
        step_row = session.execute(
            select(RunStep)
            .where(
                RunStep.tenant_id == tenant_id,
                RunStep.run_id == run_id,
                RunStep.step_key == input.step_key,
                RunStep.status == STEP_RUN_STATUS_RUNNING,
            )
            .order_by(RunStep.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if step_row is not None:
            step_row.status = input.status
            step_row.error = _truncate(input.error)
            step_row.completed_at = datetime.now(UTC)

        run = session.get(Run, run_id)
        assert run is not None
        if input.context_update:
            merged = dict(run.context)
            merged.update(input.context_update)
            run.context = merged
        # A step finishing always ends any "waiting" window -- cleared
        # here defensively even though the next `record_step_started_activity`
        # call would also clear it, so a run that completes/fails
        # immediately after its own wait step never leaves a stale,
        # non-null `waiting_for_event_type` behind (harmless for
        # `signal_run()`'s own security check, which looks at `status`
        # first, but incorrect business state otherwise).
        run.waiting_for_event_type = None
        actor_user_id = run.actor_user_id
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action=f"automation.durable_run.step_{input.status}",
        resource_type="automation.durable_run",
        resource_id=input.run_id,
        outcome=AuditOutcome.SUCCESS if input.status != "failed" else AuditOutcome.FAILURE,
        metadata={"step_key": input.step_key},
    )


@dataclass(frozen=True, slots=True)
class FinishRunInput:
    tenant_id: str
    run_id: str
    status: str
    error: str | None = None


@activity.defn
def finish_run_activity(input: FinishRunInput) -> None:
    tenant_id = uuid.UUID(input.tenant_id)
    run_id = uuid.UUID(input.run_id)
    with tenant_session_scope(tenant_id) as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.status = input.status
        run.error = _truncate(input.error)
        run.completed_at = datetime.now(UTC)
        actor_user_id = run.actor_user_id
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action=f"automation.durable_run.{input.status}",
        resource_type="automation.durable_run",
        resource_id=input.run_id,
        outcome=(
            AuditOutcome.SUCCESS if input.status == RUN_STATUS_COMPLETED else AuditOutcome.FAILURE
        ),
    )


ACTIVITIES = [
    execute_step_action_activity,
    start_run_activity,
    record_step_started_activity,
    record_step_finished_activity,
    finish_run_activity,
]

__all__ = [
    "ACTIVITIES",
    "ExecuteStepActionInput",
    "ExecuteStepActionOutput",
    "FinishRunInput",
    "StartRunInput",
    "StepFinishedInput",
    "StepStartedInput",
    "execute_step_action_activity",
    "finish_run_activity",
    "record_step_finished_activity",
    "record_step_started_activity",
    "start_run_activity",
]
