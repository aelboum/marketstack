"""The production multi-step durable workflow (docs/ROADMAP.md Phase
10.3). One Temporal workflow definition drives every published
`WorkflowVersion`'s own step graph -- the graph itself (which steps,
which branches, which action) is *data* (`DurableWorkflowInput.steps`,
copied verbatim from `WorkflowVersion.steps` at run-start), never a
second workflow class per definition.

**Determinism boundary, enforced by construction.** This file's own
`run()` method performs exactly three kinds of operation: `await
workflow.execute_activity(...)` (all business logic --
`business_activities.py`), `await asyncio.sleep(...)` (Temporal's own
durable timer, the `delay` step type), and a pure, in-memory call to
`product.automation.conditions.evaluate_conditions()` (no I/O -- see
that module's own implementation) to decide a `condition` step's
branch. No SQL, no network call, no filesystem access, no random number
generation, no uncontrolled wall-clock read, no `core.rbac` call, no
`core.audit_log` write happens anywhere in this file -- every one of
those lives in `business_activities.py`, one layer down, exactly the
boundary `docs/ADR/0007-automation-execution-substrate.md`'s own Phase
10.3 spike section already established and this phase's own
instructions restate ("do not put business logic directly into Temporal
workflow code").

**Execution-time authorization, restated for this file specifically**:
this workflow never makes, caches, or forwards an authorization
decision. `actor_user_id` is carried as plain, opaque workflow input
(never inspected, never branched on) and handed to
`execute_step_action_activity`, which re-authorizes at the instant each
action step actually executes (`business_activities.py`'s own module
docstring) -- true on the very first execution and identically true on
a Temporal-replayed retry after a crash, a pause spanning days, or a
worker restart, because the underlying `core.rbac.can()` call is live
and uncached regardless of when or how many times it runs.

**Event security for `wait_for_event` steps**: a workflow only ever
resumes from a signal it itself is currently waiting for -- `submit_event()`
silently ignores any signal whose `event_type` does not match the step
currently in flight (`_expected_event_type`), so a stale, duplicate, or
mismatched signal can never advance execution past the wrong step. This
is necessary but not sufficient for tenant isolation on its own: the
*only* way to deliver a signal to a specific execution at all is to hold
a `WorkflowHandle` for its exact `temporal_workflow_id`
(`temporalio.client.Client.get_workflow_handle()`), and
`product/automation/durable/runs.py::signal_run()` -- never this file --
is what resolves a `run_id` to that handle, only after confirming the
caller's tenant owns that run and holds the required permission. A
signal payload's own `tenant_id` (if any) is never trusted for routing;
routing happens entirely through which `WorkflowHandle` the caller was
even able to construct.

**Cancellation**: deliberately not caught here. Temporal's own
cancellation delivery (raised at the workflow's current await point when
`WorkflowHandle.cancel()` is called externally) is allowed to propagate
unhandled -- the SDK itself then ends this execution in the `CANCELED`
state, and by definition no `await workflow.execute_activity(...)` below
the point of cancellation ever starts (this phase's own "no new business
activity is started after cancellation" requirement, satisfied
structurally, not by a try/except added here). `Run.status` is set to
`cancelled` in Product Postgres by `runs.py::cancel_run()` directly, at
the moment cancellation is *requested* -- not from inside this workflow,
and not dependent on this workflow's own cleanup ever running (this
phase's own "no compensation/saga behavior in this phase": a cancelled
run's already-executed steps are not undone, mirrors
`product/automation/dispatcher.py`'s own 10.2 rollback precedent).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    # Both imports are pure/deterministic (module docstring) -- safe to
    # pass through the sandbox unchanged, the identical pattern
    # `product/automation/durable/workflows.py` (Phase 10.3 infra spike)
    # already established for its own activities.py import.
    from product.automation.conditions import evaluate_conditions
    from product.automation.durable.business_activities import (
        ExecuteStepActionInput,
        FinishRunInput,
        StartRunInput,
        StepFinishedInput,
        StepStartedInput,
        execute_step_action_activity,
        finish_run_activity,
        record_step_finished_activity,
        record_step_started_activity,
        start_run_activity,
    )
    from product.automation.durable.dsl import (
        STEP_TYPE_ACTION,
        STEP_TYPE_CONDITION,
        STEP_TYPE_DELAY,
        STEP_TYPE_WAIT_FOR_EVENT,
    )
    from product.automation.durable.models import RUN_STATUS_COMPLETED, RUN_STATUS_FAILED

# A distinct task queue from the Phase 10.3 infrastructure spike's own
# `automation-durable-spike` default (`config.py::DEFAULT_TASK_QUEUE`) --
# production runs and the spike's own probe workflow are never mixed on
# the same queue/worker. Referenced by both `runs.py` (submission) and
# `worker.py` (registration) so the two can never silently drift apart.
PRODUCTION_TASK_QUEUE = "automation-durable-production"

_BOOKKEEPING_TIMEOUT = timedelta(seconds=30)
_ACTION_ACTIVITY_TIMEOUT = timedelta(seconds=60)
# Bounded and explicit (this phase's own "keep retry policy bounded"
# requirement) -- ApplicationError(non_retryable=True) already stops a
# permanent failure (denied authorization, invalid config) immediately,
# regardless of this ceiling; this bounds genuinely transient failures
# only (a momentary DB hiccup, a flaky outbound webhook target).
_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)


@dataclass(frozen=True, slots=True)
class DurableWorkflowInput:
    tenant_id: str
    run_id: str
    actor_user_id: str
    start_step_key: str
    steps: list
    context: dict


@dataclass(frozen=True, slots=True)
class DurableWorkflowResult:
    status: str
    error: str | None
    context: dict


@dataclass(frozen=True, slots=True)
class WorkflowEventSignal:
    """Bounded signal payload for a `wait_for_event` step.
    `payload` is a small, JSON-serializable dict -- ids and scalars,
    never a full business record (module docstring's own "Event
    security" section, and `client.py`'s own "Privacy / history"
    section from the Phase 10.3 infrastructure spike, extended here)."""

    event_type: str
    payload: dict = field(default_factory=dict)


@workflow.defn
class DurableWorkflow:
    def __init__(self) -> None:
        self._expected_event_type: str | None = None
        self._received_signal: WorkflowEventSignal | None = None

    @workflow.signal
    def submit_event(self, signal: WorkflowEventSignal) -> None:
        """Ignored (not an error -- a workflow that received a stray
        signal must not crash) unless it matches the event type the
        currently in-flight `wait_for_event` step actually expects --
        module docstring's own "Event security" section."""
        if self._expected_event_type is not None and signal.event_type == self._expected_event_type:
            self._received_signal = signal

    @workflow.run
    async def run(self, input: DurableWorkflowInput) -> DurableWorkflowResult:
        by_key = {step["step_key"]: step for step in input.steps}
        context = dict(input.context)

        await workflow.execute_activity(
            start_run_activity,
            StartRunInput(tenant_id=input.tenant_id, run_id=input.run_id),
            start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
        )

        step_key: str | None = input.start_step_key
        while step_key is not None:
            step = by_key[step_key]
            step_type = step["type"]
            await workflow.execute_activity(
                record_step_started_activity,
                StepStartedInput(
                    tenant_id=input.tenant_id,
                    run_id=input.run_id,
                    step_key=step_key,
                    step_type=step_type,
                    waiting_for_event_type=(
                        step["event_type"] if step_type == STEP_TYPE_WAIT_FOR_EVENT else None
                    ),
                ),
                start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
            )

            if step_type == STEP_TYPE_ACTION:
                step_key, context, failure = await self._run_action_step(
                    input, step_key, step, context
                )
                if failure is not None:
                    await self._finish(input, RUN_STATUS_FAILED, failure, context)
                    return DurableWorkflowResult(
                        status=RUN_STATUS_FAILED, error=failure, context=context
                    )

            elif step_type == STEP_TYPE_CONDITION:
                matched = evaluate_conditions(step["conditions"], context)
                await workflow.execute_activity(
                    record_step_finished_activity,
                    StepFinishedInput(
                        tenant_id=input.tenant_id,
                        run_id=input.run_id,
                        step_key=step_key,
                        status="succeeded",
                    ),
                    start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
                )
                step_key = (
                    step.get("next_step_key_true") if matched else step.get("next_step_key_false")
                )

            elif step_type == STEP_TYPE_DELAY:
                await asyncio.sleep(step["delay_seconds"])
                await workflow.execute_activity(
                    record_step_finished_activity,
                    StepFinishedInput(
                        tenant_id=input.tenant_id,
                        run_id=input.run_id,
                        step_key=step_key,
                        status="succeeded",
                    ),
                    start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
                )
                step_key = step.get("next_step_key")

            else:  # STEP_TYPE_WAIT_FOR_EVENT
                step_key, context, failure = await self._run_wait_step(
                    input, step_key, step, context
                )
                if failure is not None:
                    await self._finish(input, RUN_STATUS_FAILED, failure, context)
                    return DurableWorkflowResult(
                        status=RUN_STATUS_FAILED, error=failure, context=context
                    )

        await self._finish(input, RUN_STATUS_COMPLETED, None, context)
        return DurableWorkflowResult(status=RUN_STATUS_COMPLETED, error=None, context=context)

    async def _run_action_step(
        self, input: DurableWorkflowInput, step_key: str, step: dict, context: dict
    ) -> tuple[str | None, dict, str | None]:
        try:
            output = await workflow.execute_activity(
                execute_step_action_activity,
                ExecuteStepActionInput(
                    tenant_id=input.tenant_id,
                    run_id=input.run_id,
                    step_key=step_key,
                    actor_user_id=input.actor_user_id,
                    action_type=step["action_type"],
                    action_config=step.get("action_config") or {},
                    context=context,
                ),
                start_to_close_timeout=_ACTION_ACTIVITY_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )
        except ActivityError as exc:
            error_text = str(exc.cause) if exc.cause is not None else str(exc)
            await workflow.execute_activity(
                record_step_finished_activity,
                StepFinishedInput(
                    tenant_id=input.tenant_id,
                    run_id=input.run_id,
                    step_key=step_key,
                    status="failed",
                    error=error_text,
                ),
                start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
            )
            return None, context, error_text

        new_context = dict(context)
        new_context.update(output.result)
        await workflow.execute_activity(
            record_step_finished_activity,
            StepFinishedInput(
                tenant_id=input.tenant_id,
                run_id=input.run_id,
                step_key=step_key,
                status="succeeded",
                context_update=output.result,
            ),
            start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
        )
        return step.get("next_step_key"), new_context, None

    async def _run_wait_step(
        self, input: DurableWorkflowInput, step_key: str, step: dict, context: dict
    ) -> tuple[str | None, dict, str | None]:
        """Returns `(next_step_key, context, failure)`. `failure` is
        non-`None` only when the wait timed out AND the step defines no
        `timeout_step_key` fallback -- that specific combination means
        the run itself failed, not merely that this one step did
        (distinct from every other timeout case, which instead branches
        to `timeout_step_key` and continues -- the caller must not
        conflate "next_step_key is None because the graph finished
        normally" with "next_step_key is None because there was nowhere
        to go after an unhandled timeout")."""
        self._expected_event_type = step["event_type"]
        self._received_signal = None
        try:
            await workflow.wait_condition(
                lambda: self._received_signal is not None,
                timeout=timedelta(seconds=step["timeout_seconds"]),
            )
        except TimeoutError:
            await workflow.execute_activity(
                record_step_finished_activity,
                StepFinishedInput(
                    tenant_id=input.tenant_id,
                    run_id=input.run_id,
                    step_key=step_key,
                    status="failed",
                    error="wait_for_event timed out",
                ),
                start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
            )
            timeout_step_key = step.get("timeout_step_key")
            failure = "wait_for_event timed out" if timeout_step_key is None else None
            return timeout_step_key, context, failure
        finally:
            self._expected_event_type = None

        received = self._received_signal
        assert received is not None  # wait_condition only returns once this is true
        new_context = dict(context)
        new_context[f"{step_key}.event"] = received.payload
        await workflow.execute_activity(
            record_step_finished_activity,
            StepFinishedInput(
                tenant_id=input.tenant_id,
                run_id=input.run_id,
                step_key=step_key,
                status="succeeded",
                context_update={f"{step_key}.event": received.payload},
            ),
            start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
        )
        return step.get("next_step_key"), new_context, None

    async def _finish(
        self, input: DurableWorkflowInput, status: str, error: str | None, context: dict
    ) -> None:
        await workflow.execute_activity(
            finish_run_activity,
            FinishRunInput(
                tenant_id=input.tenant_id, run_id=input.run_id, status=status, error=error
            ),
            start_to_close_timeout=_BOOKKEEPING_TIMEOUT,
        )
