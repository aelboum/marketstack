"""Durable run submission/observation/cancellation/signaling
(docs/ROADMAP.md Phase 10.3). Mirrors `product/automation/dispatcher.py`'s
own SAVEPOINT-based reservation discipline (idempotent run creation) and
`product/automation/workflows.py`'s own authorize-then-mutate-then-audit
shape, extended with the one genuinely new ingredient this phase adds:
calls into the Temporal client (`temporalio.client.Client`), which is
`async def`-only -- every function here that talks to Temporal is
therefore `async def` too, called directly by this phase's own `async
def` API routes (`routes.py`) with no `asyncio.run()` bridge anywhere
(this module's own docstring continues below on exactly why that is
safe here and was not safe for 10.2's own sync event publishers).

**Deterministic, tenant-safe Temporal workflow IDs, never naive prefix
matching.** `_temporal_workflow_id()` embeds `tenant_id.hex` and
`run_id.hex` -- both always genuine `uuid.UUID` values by the time this
module ever constructs an id (never a raw, attacker-influenced string:
every caller already went through FastAPI's own `uuid.UUID` path-param
coercion or a `uuid.UUID(...)` conversion of an authenticated actor id).
Using `.hex` (32 lowercase-hex characters, no `-`, no `:`) rather than
the canonical dashed form removes even the possibility of the
tenant-id-embeds-a-delimiter collision the Phase 10.3 infrastructure
spike found and fixed in its own probe-workflow id convention
(`product/automation/durable/client.py`'s own module docstring) -- here
that collision class cannot exist at all, structurally, because neither
segment is ever an arbitrary string to begin with.

**Every business action re-authorizes at execution time -- restated
here because it is this phase's own most safety-critical property.**
`start_run()` authorizes *submission* only (`DURABLE_WORKFLOW_RESOURCE`,
`"execute"`) -- it is not sufficient, and is never treated as
sufficient, for any step's own business action, which
`business_activities.py::execute_step_action_activity()` re-authorizes
independently, every time, using `Run.actor_user_id`. Revoking that
user's own CRM/email/webhook permission between submission and a later
step denies that later step exactly as it would deny the same user
acting directly -- proven for the single-step 10.2 engine already
(`docs/ROADMAP.md` Phase 10.2's own adversarial test,
`tests/automation/test_dispatcher_integration.py
::test_workflow_cannot_exceed_creators_own_revoked_permissions`), and
covered again here by this phase's own equivalent multi-step test.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.automation.durable.client import get_client
from product.automation.durable.dsl import WAITABLE_EVENT_TYPES
from product.automation.durable.models import (
    MAX_DEDUP_KEY_LENGTH,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_QUEUED,
    RUN_STATUS_WAITING,
    STATUS_ACTIVE,
    TERMINAL_RUN_STATUSES,
    VERSION_STATUS_PUBLISHED,
    Run,
    RunStep,
    Workflow,
    WorkflowVersion,
)
from product.automation.durable.permissions import DURABLE_WORKFLOW_RESOURCE, require
from product.automation.durable.production_workflow import (
    PRODUCTION_TASK_QUEUE,
    DurableWorkflow,
    DurableWorkflowInput,
    WorkflowEventSignal,
)
from product.automation.errors import AutomationReferenceNotFoundError, AutomationValidationError
from product.automation.pagination import DEFAULT_PAGE_SIZE, clamp_limit

MAX_CONTEXT_JSON_CHARS = 8_000


def _temporal_workflow_id(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    """Module docstring's own "deterministic, tenant-safe Temporal
    workflow IDs" section -- both segments are always real `uuid.UUID`
    values, never an arbitrary string, so this can never collide the way
    a naive prefix-matched, attacker-influenced id could."""
    return f"automation-durable-run:{tenant_id.hex}:{run_id.hex}"


def _reserve_run(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    workflow_version_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    dedup_key: str,
    context: dict,
) -> uuid.UUID | None:
    """SAVEPOINT-based idempotent reservation -- identical discipline to
    `product/automation/dispatcher.py::_record_run()`. Returns the new
    `Run.id` on success, `None` if this exact `(tenant_id, workflow_id,
    dedup_key)` was already reserved (caller must not submit a second
    Temporal execution for it)."""
    run_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            with session.begin_nested():
                session.add(
                    Run(
                        id=run_id,
                        tenant_id=tenant_id,
                        workflow_id=workflow_id,
                        workflow_version_id=workflow_version_id,
                        status=RUN_STATUS_QUEUED,
                        actor_user_id=actor_user_id,
                        trigger_dedup_key=dedup_key,
                        context=context,
                    )
                )
                session.flush()
        return run_id
    except IntegrityError:
        return None


async def _submit_run_to_temporal(tenant_id: uuid.UUID, run: Run, version: WorkflowVersion) -> None:
    """The `queued -> running` handoff (models.py's own module
    docstring): calls Temporal's own `start_workflow`, then records the
    resulting `temporal_workflow_id`/`temporal_run_id` back onto the
    `Run` row. `product/automation/durable/business_activities.py
    ::start_run_activity` (run from *inside* the now-started workflow)
    is what actually flips `status` to `running` -- this function's own
    job is only ever getting the execution started at all."""
    temporal_workflow_id = _temporal_workflow_id(tenant_id, run.id)
    client = await get_client()
    handle = await client.start_workflow(
        DurableWorkflow.run,
        DurableWorkflowInput(
            tenant_id=str(tenant_id),
            run_id=str(run.id),
            actor_user_id=str(run.actor_user_id),
            start_step_key=version.start_step_key,
            steps=list(version.steps),
            context=dict(run.context),
        ),
        id=temporal_workflow_id,
        task_queue=PRODUCTION_TASK_QUEUE,
    )
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run.id)
        if row is not None:
            row.temporal_workflow_id = temporal_workflow_id
            row.temporal_run_id = handle.result_run_id
            session.flush()


def _validate_context(context: dict) -> None:
    encoded = json.dumps(context, default=str)
    if len(encoded) > MAX_CONTEXT_JSON_CHARS:
        raise AutomationValidationError(f"context exceeds {MAX_CONTEXT_JSON_CHARS} characters.")


async def start_run(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    context: dict | None = None,
    idempotency_key: str | None = None,
) -> RunView:
    """Manually starts one run of `workflow_id`'s own currently-published
    version. `idempotency_key` (optional, caller-supplied) lets a caller
    make a repeated start-run request safely re-entrant -- omitted, a
    fresh key is generated so every call starts a genuinely new run."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="execute")
    context = context or {}
    _validate_context(context)
    dedup_key = (idempotency_key or uuid.uuid4().hex)[:MAX_DEDUP_KEY_LENGTH]

    with tenant_session_scope(tenant_id) as session:
        workflow_row = session.get(Workflow, workflow_id)
        if workflow_row is None or workflow_row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        if workflow_row.status != STATUS_ACTIVE:
            raise AutomationValidationError(
                "workflow is disabled -- enable it before starting a run."
            )
        if workflow_row.current_published_version_id is None:
            raise AutomationValidationError("workflow has no published version.")
        version_row = session.get(WorkflowVersion, workflow_row.current_published_version_id)
        assert version_row is not None and version_row.status == VERSION_STATUS_PUBLISHED
        session.expunge(version_row)

    run_id = _reserve_run(tenant_id, workflow_id, version_row.id, actor_user_id, dedup_key, context)
    if run_id is None:
        raise AutomationValidationError(
            f"a run with idempotency key {dedup_key!r} already exists for this workflow."
        )

    with tenant_session_scope(tenant_id) as session:
        run_row = session.get(Run, run_id)
        assert run_row is not None
        session.expunge(run_row)

    await _submit_run_to_temporal(tenant_id, run_row, version_row)

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run_id)
        assert row is not None
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_run.submitted",
        resource_type="automation.durable_run",
        resource_id=str(run_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"workflow_id": str(workflow_id)},
    )
    return _run_to_view(row)


async def cancel_run(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, run_id: uuid.UUID, *, reason: str
) -> RunView:
    """Product-authorized cancellation. Cross-tenant cancellation is
    rejected by the same `session.get(Run, run_id)` + `tenant_id`-scoped
    `tenant_session_scope()` every other lookup in this module already
    uses (RLS-backed -- a run belonging to a different tenant is not
    merely filtered, it is unreachable through this tenant's own scoped
    session at all)."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="cancel")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("run", run_id)
        if row.status in TERMINAL_RUN_STATUSES:
            raise AutomationValidationError(f"run is already {row.status} -- nothing to cancel.")
        temporal_workflow_id = row.temporal_workflow_id

    if temporal_workflow_id is not None:
        client = await get_client()
        handle = client.get_workflow_handle(temporal_workflow_id)
        await handle.cancel()

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run_id)
        assert row is not None
        row.status = RUN_STATUS_CANCELLED
        row.completed_at = datetime.now(UTC)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_run.cancelled",
        resource_type="automation.durable_run",
        resource_id=str(run_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"reason": reason[:255]},
    )
    return _run_to_view(row)


async def signal_run(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    event_type: str,
    payload: dict | None = None,
) -> None:
    """Resumes a `waiting` run's own `wait_for_event` step. Every one of
    this phase's own required validations happens here, in order, before
    Temporal is ever contacted: the run belongs to this tenant (or is not
    found at all -- non-enumerating), the actor is authorized, the run is
    actually `waiting`, and `event_type` matches
    `Run.waiting_for_event_type` exactly -- a mismatch is rejected here
    (`AutomationValidationError`), never forwarded to Temporal as a
    signal the workflow's own handler would also reject (module
    docstring's own "Event security" -- redundant-by-design defense in
    depth with `production_workflow.py::DurableWorkflow.submit_event()`'s
    own identical check)."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="signal")
    if event_type not in WAITABLE_EVENT_TYPES:
        raise AutomationValidationError(f"unknown event_type: {event_type!r}.")
    payload = payload or {}
    _validate_context(payload)

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("run", run_id)
        if row.status != RUN_STATUS_WAITING:
            raise AutomationValidationError("run is not currently waiting for an event.")
        if row.waiting_for_event_type != event_type:
            raise AutomationValidationError(
                f"run is waiting for {row.waiting_for_event_type!r}, not {event_type!r}."
            )
        temporal_workflow_id = row.temporal_workflow_id
        assert temporal_workflow_id is not None  # status == waiting implies it was submitted

    client = await get_client()
    handle = client.get_workflow_handle(temporal_workflow_id)
    signal = WorkflowEventSignal(event_type=event_type, payload=payload)
    await handle.signal(DurableWorkflow.submit_event, signal)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_run.signalled",
        resource_type="automation.durable_run",
        resource_id=str(run_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"event_type": event_type},
    )


@dataclass(frozen=True, slots=True)
class RunView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_version_id: uuid.UUID
    status: str
    actor_user_id: uuid.UUID
    # Never Temporal's internal API surface -- an opaque identifier only
    # (this module's own module docstring's "deterministic, tenant-safe
    # Temporal workflow IDs" section); `None` until `_submit_run_to_temporal()`
    # actually starts the execution (the `queued -> running` handoff).
    temporal_workflow_id: str | None
    current_step_key: str | None
    waiting_for_event_type: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


def _run_to_view(row: Run) -> RunView:
    return RunView(
        id=row.id,
        tenant_id=row.tenant_id,
        workflow_id=row.workflow_id,
        workflow_version_id=row.workflow_version_id,
        status=row.status,
        actor_user_id=row.actor_user_id,
        temporal_workflow_id=row.temporal_workflow_id,
        current_step_key=row.current_step_key,
        waiting_for_event_type=row.waiting_for_event_type,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def get_run(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, run_id: uuid.UUID) -> RunView:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Run, run_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("run", run_id)
        session.expunge(row)
    return _run_to_view(row)


def list_runs(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[RunView]:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Run)
                .where(Run.tenant_id == tenant_id, Run.workflow_id == workflow_id)
                .order_by(Run.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_run_to_view(row) for row in rows]


@dataclass(frozen=True, slots=True)
class RunStepView:
    id: uuid.UUID
    run_id: uuid.UUID
    step_key: str
    step_type: str
    status: str
    error: str | None
    started_at: datetime
    completed_at: datetime | None


def list_run_steps(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> list[RunStepView]:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        run_row = session.get(Run, run_id)
        if run_row is None or run_row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("run", run_id)
        rows = (
            session.execute(
                select(RunStep)
                .where(RunStep.tenant_id == tenant_id, RunStep.run_id == run_id)
                .order_by(RunStep.started_at.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [
        RunStepView(
            id=r.id,
            run_id=r.run_id,
            step_key=r.step_key,
            step_type=r.step_type,
            status=r.status,
            error=r.error,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in rows
    ]


__all__ = [
    "RunStepView",
    "RunView",
    "cancel_run",
    "get_run",
    "list_run_steps",
    "list_runs",
    "signal_run",
    "start_run",
]
