"""Production multi-step durable workflow execution -- docs/ROADMAP.md
Phase 10.3's own required EXECUTION / FAILURE-RECOVERY / AUTHORIZATION /
TENANT LIFECYCLE / PRIVACY test groups. Marked BOTH `integration` (real
disposable Postgres, tenant/RBAC/CRM state) AND `temporal` (a real
ephemeral Temporal test server per test, via `temporalio.testing
.WorkflowEnvironment`) -- excluded from the default `pytest` run and
from the plain `integration`-only run (`scripts/check-integration.sh`
now runs `-m "integration and not temporal"` specifically so it never
needs outbound network access). Run explicitly, against an
already-provisioned disposable Postgres (`DATABASE_URL` etc. already
exported, exactly as `scripts/check-integration.sh` itself does):

    pytest tests/automation/durable/production -m "integration and temporal"

Every test drives the *real* production service layer
(`product.automation.durable.runs`) -- `runs.get_client` is monkeypatched
only at the one seam that would otherwise require a real, externally
configured `TEMPORAL_ADDRESS` (`_harness()` below), never the business
logic itself. Every activity is the real, unmodified
`product.automation.durable.business_activities`, run through a real
`temporalio.worker.Worker` with a real `ThreadPoolExecutor` -- the exact
production wiring `production_worker.py` uses, not a stub.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import pytest
from core.audit_log import list as list_audit_log
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.automation.durable import definitions, runs
from product.automation.durable.models import (
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_WAITING,
)
from product.automation.durable.production_workflow import (
    PRODUCTION_TASK_QUEUE,
    DurableWorkflow,
)
from product.automation.errors import (
    AutomationAccessDeniedError,
    AutomationReferenceNotFoundError,
)
from product.crm.activities import TaskView, list_activities
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.temporal]

_TERMINAL = (RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _action_step(step_key: str, *, title: str, next_step_key: str | None = None) -> dict:
    return {
        "step_key": step_key,
        "type": "action",
        "action_type": "create_task",
        "action_config": {"title": title},
        "next_step_key": next_step_key,
    }


def _publish(owner_id, tenant_id, *, start_step_key: str, steps: list):
    workflow, version = definitions.create_workflow(
        owner_id, tenant_id, name=_name("wf"), start_step_key=start_step_key, steps=steps
    )
    published = definitions.publish_version(owner_id, tenant_id, workflow.id, version.id)
    return workflow, published


def _temporal_id(run_view: runs.RunView) -> str:
    """`start_run()` always sets `Run.temporal_workflow_id` synchronously
    before returning (`runs.py::_submit_run_to_temporal()`) -- this
    narrows the type for every call site below, which only ever calls it
    on a `RunView` already returned by `start_run()`."""
    assert run_view.temporal_workflow_id is not None
    return run_view.temporal_workflow_id


def _fake_get_client(env):
    """The one patched seam (module docstring): a `get_client()`-shaped
    coroutine returning this test environment's own already-connected
    client instead of dialing a real, externally configured
    `TEMPORAL_ADDRESS`."""

    async def _get_client(config=None):
        return env.client

    return _get_client


@asynccontextmanager
async def _harness(monkeypatch: pytest.MonkeyPatch, *, real_server: bool = False):
    """Yields a connected, worker-backed Temporal test environment with
    `product.automation.durable.runs.get_client` patched to return it --
    the one seam described in the module docstring. `real_server=True`
    uses `start_local()` (a real dev-server subprocess, real time, full
    Visibility API) instead of the faster in-process time-skipping
    server -- needed only by the worker-restart test below, which must
    stop and start a second, independent `Worker` object against
    server-side state that survives the first one going away."""
    env = (
        await WorkflowEnvironment.start_local()
        if real_server
        else await WorkflowEnvironment.start_time_skipping()
    )
    try:
        monkeypatch.setattr(runs, "get_client", _fake_get_client(env))
        with ThreadPoolExecutor(max_workers=8) as executor:
            worker = Worker(
                env.client,
                task_queue=PRODUCTION_TASK_QUEUE,
                workflows=[DurableWorkflow],
                activities=_activities(),
                activity_executor=executor,
            )
            async with worker:
                yield env
    finally:
        await env.shutdown()


def _activities():
    from product.automation.durable.business_activities import ACTIVITIES

    return ACTIVITIES


def _settled(view) -> bool:
    """`waiting` is a settled observation too -- a run parked on a
    `wait_for_event` step is exactly what the signal/cancel tests below
    need to see before they act on it."""
    return view.status in _TERMINAL or view.status == RUN_STATUS_WAITING


def _wait_for_terminal(actor_id, tenant_id, run_id, *, timeout_seconds: float = 20.0):
    """Synchronous poll (plain `time.sleep`, real wall-clock), used ONLY
    after `asyncio.run()` has already returned -- never from inside a
    coroutine. Polling synchronously inside the same event loop the
    `temporalio.worker.Worker` runs on starves that worker: the workflow
    task cannot make progress while this thread sleeps, so the run stays
    `queued` and the poll then "times out" on a workflow the test itself
    was blocking. `_await_run_status()` below is the in-coroutine form.
    """
    import time

    deadline = time.monotonic() + timeout_seconds
    view = runs.get_run(actor_id, tenant_id, run_id)
    while view.status not in _TERMINAL and time.monotonic() < deadline:
        time.sleep(0.1)
        view = runs.get_run(actor_id, tenant_id, run_id)
    return view


async def _await_run_status(actor_id, tenant_id, run_id, *, timeout_seconds: float = 20.0):
    """The in-coroutine poll: `await asyncio.sleep()` (yields to the
    worker's own event loop between reads) plus `asyncio.to_thread()` for
    the blocking Postgres read (`runs.get_run()` is sync). See
    `_wait_for_terminal()`'s docstring for why the synchronous form must
    never be used from inside a coroutine here."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    view = await asyncio.to_thread(runs.get_run, actor_id, tenant_id, run_id)
    while not _settled(view) and loop.time() < deadline:
        await asyncio.sleep(0.1)
        view = await asyncio.to_thread(runs.get_run, actor_id, tenant_id, run_id)
    return view


async def _await_temporal_status(handle, statuses, *, timeout_seconds: float = 20.0):
    """Cancellation and termination are both *asynchronous* on Temporal's
    own side: the server records the request, and the execution reaches
    its terminal status only once the workflow task carrying it has been
    processed. `describe()` called immediately after `cancel()` therefore
    legitimately still reports RUNNING -- the tests below must wait for
    the terminal status rather than assert on the first observation."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    description = await handle.describe()
    while description.status not in statuses and loop.time() < deadline:
        await asyncio.sleep(0.1)
        description = await handle.describe()
    return description


# --- EXECUTION ---------------------------------------------------------


def test_multi_step_action_sequencing_and_completion() -> None:
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        steps = [
            _action_step("s1", title="first", next_step_key="s2"),
            _action_step("s2", title="second", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_COMPLETED

        step_views = runs.list_run_steps(owner.id, client.tenant_id, run_id)
        assert [s.step_key for s in step_views] == ["s1", "s2"]
        assert all(s.status == "succeeded" for s in step_views)

        activities_list = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        titles = {a.title for a in activities_list if isinstance(a, TaskView)}
        assert {"first", "second"} <= titles
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_condition_true_and_false_branches() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        steps = [
            {
                "step_key": "s1",
                "type": "condition",
                "conditions": [{"field": "flag", "op": "eq", "value": "yes"}],
                "next_step_key_true": "s_true",
                "next_step_key_false": "s_false",
            },
            _action_step("s_true", title="true-branch", next_step_key=None),
            _action_step("s_false", title="false-branch", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _start(context):
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id, client.tenant_id, workflow.id, context=context
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        true_run_id = asyncio.run(_start({"flag": "yes"}))
        false_run_id = asyncio.run(_start({"flag": "no"}))

        true_steps = [
            s.step_key for s in runs.list_run_steps(owner.id, client.tenant_id, true_run_id)
        ]
        false_steps = [
            s.step_key for s in runs.list_run_steps(owner.id, client.tenant_id, false_run_id)
        ]
        assert true_steps == ["s1", "s_true"]
        assert false_steps == ["s1", "s_false"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_durable_delay_step_completes() -> None:
    """A one-hour durable delay, exercised against the time-skipping
    environment: `env.sleep()` advances the *server's* own clock past the
    Temporal timer, so this test proves the `delay` step really is a
    durable Temporal timer without waiting out an hour of real time.

    `await handle.result()` is deliberately NOT used to wait this out.
    Automatic time skipping is attached only to the handle object
    `Client.start_workflow()` itself returns (`temporalio.testing
    ._workflow._TimeSkippingClientOutboundInterceptor` swaps that one
    handle's class); a handle reconstructed from a workflow id via
    `get_workflow_handle()` -- the only kind this test can have, since
    `runs.start_run()` owns the `start_workflow()` call and returns a
    `RunView`, not a handle -- is a plain handle whose `result()` waits in
    real time and eventually raises "No completion event found"."""
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        steps = [
            {
                "step_key": "s1",
                "type": "delay",
                "delay_seconds": 3600,
                "next_step_key": "s2",
            },
            _action_step("s2", title="after-delay", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    # Still parked on the durable timer -- nothing after
                    # the delay step has run yet.
                    mid = await asyncio.to_thread(
                        runs.get_run, owner.id, client.tenant_id, run_view.id
                    )
                    assert mid.status not in _TERMINAL

                    await env.sleep(3_601)
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    final = await _await_temporal_status(
                        handle, (WorkflowExecutionStatus.COMPLETED,)
                    )
                    assert final.status == WorkflowExecutionStatus.COMPLETED
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_COMPLETED
        step_views = runs.list_run_steps(owner.id, client.tenant_id, run_id)
        assert [s.step_key for s in step_views] == ["s1", "s2"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_wait_for_event_resumes_after_signal_and_completes() -> None:
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": "s2",
                "timeout_step_key": None,
            },
            _action_step("s2", title="after-event", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))

                    # Wait for the run to actually reach WAITING in
                    # Postgres before signaling -- signal_run() itself
                    # requires status == waiting (defense in depth).
                    waiting = await _await_run_status(owner.id, client.tenant_id, run_view.id)
                    assert waiting.status == RUN_STATUS_WAITING
                    assert waiting.waiting_for_event_type == "crm.contact.created"

                    await runs.signal_run(
                        owner.id,
                        client.tenant_id,
                        run_view.id,
                        event_type="crm.contact.created",
                        payload={"contact_id": str(uuid.uuid4())},
                    )
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_COMPLETED
        step_keys = [s.step_key for s in runs.list_run_steps(owner.id, client.tenant_id, run_id)]
        assert step_keys == ["s1", "s2"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- FAILURE / RECOVERY --------------------------------------------------


def test_permanent_authorization_denial_terminates_run_correctly() -> None:
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        # A real contact, so the only reason create_task can fail is the
        # deny grant below -- never a missing-entity-id validation error.
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        # `product/crm/permissions.py` has no `crm.task` resource -- a task
        # attached to a contact is gated by that contact's own
        # `crm.contact:update` (`product/crm/activities.py::create_task()`).
        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource="crm.contact",
            action="update",
        )
        steps = [_action_step("s1", title="x", next_step_key=None)]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_FAILED
        assert final.error

        entries = list_audit_log(
            client.tenant_id,
            resource_type="automation.durable_run",
            resource_id=str(run_id),
        )
        assert any(e.action == "automation.durable_run.authorization_denied" for e in entries)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_permission_revoked_before_later_step_denies_only_that_step() -> None:
    """The core adversarial test this phase's own instructions call out
    explicitly: revoking the creator's own permission between steps must
    deny the later step at the exact authorization boundary the creator
    would hit acting directly -- never succeed on a decision cached at
    workflow-submission time."""
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": "s2",
                "timeout_step_key": None,
            },
            _action_step("s2", title="after-revoke", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))

                    waiting = await _await_run_status(owner.id, client.tenant_id, run_view.id)
                    assert waiting.status == RUN_STATUS_WAITING

                    # Revoke, mid-flight, exactly the permission
                    # `create_task()` itself checks. `product/crm/
                    # permissions.py` deliberately has no `crm.task`
                    # resource: a task attached to a contact is gated by
                    # that contact's own `crm.contact:update`.
                    create_client_deny(
                        grantor_user_id=owner.id,
                        principal_user_id=owner.id,
                        tenant_id=client.tenant_id,
                        resource="crm.contact",
                        action="update",
                    )

                    await runs.signal_run(
                        owner.id,
                        client.tenant_id,
                        run_view.id,
                        event_type="crm.contact.created",
                        payload={},
                    )
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_FAILED

        step_views = runs.list_run_steps(owner.id, client.tenant_id, run_id)
        by_key = {s.step_key: s for s in step_views}
        assert by_key["s1"].status == "succeeded"  # the wait step itself always "succeeds"
        assert by_key["s2"].status == "failed"  # denied at execution time
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_activity_execution_remains_idempotent() -> None:
    """Calls the real activity function directly (bypassing Temporal
    entirely -- it makes no call into the SDK's own execution-context
    accessors, `business_activities.py`'s own module docstring) twice
    with the identical `(run_id, step_key)` idempotency key, proving a
    Temporal-retried invocation cannot double-create the same task."""
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")

        from product.automation.durable.business_activities import (
            ExecuteStepActionInput,
            execute_step_action_activity,
        )

        run_id = str(uuid.uuid4())
        step_input = ExecuteStepActionInput(
            tenant_id=str(client.tenant_id),
            run_id=run_id,
            step_key="s1",
            actor_user_id=str(owner.id),
            action_type="create_task",
            action_config={"title": "idempotent-task"},
            context={"contact_id": str(contact.id)},
        )

        first = asyncio.run(_call_activity(execute_step_action_activity, step_input))
        second = asyncio.run(_call_activity(execute_step_action_activity, step_input))
        assert first.result == second.result  # the replayed result, not a second real task

        activities_list = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        matching = [
            a for a in activities_list if isinstance(a, TaskView) and a.title == "idempotent-task"
        ]
        assert len(matching) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def _call_activity(fn, arg):
    return fn(arg)


def test_worker_restart_resumes_waiting_workflow() -> None:
    """Stops the first `Worker` entirely and starts a brand-new, separate
    `Worker` object against the same real dev-server (`start_local()`,
    not time-skipping -- real Visibility/persistence, mirrors the Phase
    10.3 infrastructure spike's own restart-proof methodology at the
    workflow-code level) while a run is genuinely `waiting`, proving the
    execution survives having no worker present for a real interval."""
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": "s2",
                "timeout_step_key": None,
            },
            _action_step("s2", title="after-restart", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            env = await WorkflowEnvironment.start_local()
            try:
                monkeypatch = pytest.MonkeyPatch()

                async def _fake_get_client(config=None):
                    return env.client

                monkeypatch.setattr(runs, "get_client", _fake_get_client)
                try:
                    from product.automation.durable.business_activities import ACTIVITIES

                    with ThreadPoolExecutor(max_workers=8) as executor1:
                        worker1 = Worker(
                            env.client,
                            task_queue=PRODUCTION_TASK_QUEUE,
                            workflows=[DurableWorkflow],
                            activities=ACTIVITIES,
                            activity_executor=executor1,
                        )
                        async with worker1:
                            run_view = await runs.start_run(
                                owner.id,
                                client.tenant_id,
                                workflow.id,
                                context={"contact_id": str(contact.id)},
                            )
                            for _ in range(100):
                                current = runs.get_run(owner.id, client.tenant_id, run_view.id)
                                if current.status == RUN_STATUS_WAITING:
                                    break
                                await asyncio.sleep(0.1)
                            assert current.status == RUN_STATUS_WAITING
                    # worker1's own `async with` block has now exited --
                    # no worker is polling the task queue at all.

                    await runs.signal_run(
                        owner.id,
                        client.tenant_id,
                        run_view.id,
                        event_type="crm.contact.created",
                        payload={},
                    )

                    with ThreadPoolExecutor(max_workers=8) as executor2:
                        worker2 = Worker(
                            env.client,
                            task_queue=PRODUCTION_TASK_QUEUE,
                            workflows=[DurableWorkflow],
                            activities=ACTIVITIES,
                            activity_executor=executor2,
                        )
                        async with worker2:
                            handle = env.client.get_workflow_handle(_temporal_id(run_view))
                            await handle.result()
                    return run_view.id
                finally:
                    monkeypatch.undo()
            finally:
                await env.shutdown()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner.id, client.tenant_id, run_id)
        assert final.status == RUN_STATUS_COMPLETED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- CANCELLATION ---------------------------------------------------------


def test_cancellation_stops_future_work() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": "s2",
                "timeout_step_key": None,
            },
            _action_step("s2", title="never-runs", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(owner.id, client.tenant_id, workflow.id)
                    waiting = await _await_run_status(owner.id, client.tenant_id, run_view.id)
                    assert waiting.status == RUN_STATUS_WAITING

                    cancelled = await runs.cancel_run(
                        owner.id, client.tenant_id, run_view.id, reason="test cancellation"
                    )
                    assert cancelled.status == RUN_STATUS_CANCELLED

                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    terminal = (
                        WorkflowExecutionStatus.CANCELED,
                        WorkflowExecutionStatus.TERMINATED,
                    )
                    description = await _await_temporal_status(handle, terminal)
                    assert description.status in terminal
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        # No CRM entity exists in this test (the cancelled run never reached
        # s2's own `create_task`), so `list_activities()`'s entity-scoped
        # contract (exactly one of contact_id/company_id/opportunity_id)
        # cannot be used here -- the engine's own `RunStep` record is the
        # direct, correct way to prove "s2" never ran at all.
        step_views = runs.list_run_steps(owner.id, client.tenant_id, run_id)
        assert not any(s.step_key == "s2" for s in step_views)
        entries = list_audit_log(
            client.tenant_id, resource_type="automation.durable_run", resource_id=str(run_id)
        )
        assert any(e.action == "automation.durable_run.cancelled" for e in entries)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- TENANT ISOLATION -----------------------------------------------------


def test_cross_tenant_signal_and_cancel_and_read_rejected() -> None:
    owner_a = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    owner_b = make_user()
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": None,
                "timeout_step_key": None,
            }
        ]
        workflow, _version = _publish(
            owner_a.id, client_a.tenant_id, start_step_key="s1", steps=steps
        )

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch):
                    run_view = await runs.start_run(owner_a.id, client_a.tenant_id, workflow.id)
                    await _await_run_status(owner_a.id, client_a.tenant_id, run_view.id)

                    with pytest.raises(AutomationReferenceNotFoundError):
                        runs.get_run(owner_b.id, client_b.tenant_id, run_view.id)

                    with pytest.raises(AutomationReferenceNotFoundError):
                        await runs.signal_run(
                            owner_b.id,
                            client_b.tenant_id,
                            run_view.id,
                            event_type="crm.contact.created",
                            payload={},
                        )

                    with pytest.raises(AutomationReferenceNotFoundError):
                        await runs.cancel_run(
                            owner_b.id, client_b.tenant_id, run_view.id, reason="cross-tenant"
                        )

                    # Cleanup: cancel it for real, as its own owner.
                    await runs.cancel_run(
                        owner_a.id, client_a.tenant_id, run_view.id, reason="test cleanup"
                    )
            finally:
                monkeypatch.undo()

        asyncio.run(_run())
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- TENANT PURGE -----------------------------------------------------


def test_purge_terminates_active_run_and_prevents_resume() -> None:
    from core.tenancy import TenantStatus, purge_tenant, transition_tenant_status
    from core.tenancy.purge_participants import TenantPurgeParticipantRegistry
    from product.automation import purge as automation_purge
    from product.automation.purge import AutomationDataPurgeParticipant

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": None,
                "timeout_step_key": None,
            }
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(owner.id, client.tenant_id, workflow.id)
                    await _await_run_status(owner.id, client.tenant_id, run_view.id)

                    registry = TenantPurgeParticipantRegistry()
                    registry.register(AutomationDataPurgeParticipant())
                    # `product/automation/purge.py` imports `get_client`
                    # from `product.automation.durable.client` directly,
                    # so `_harness()`'s patch of `runs.get_client` does
                    # not cover it -- without this, the participant would
                    # try to reach a real, unconfigured TEMPORAL_ADDRESS.
                    # Same single seam, patched in the second module that
                    # legitimately uses it.
                    monkeypatch.setattr(automation_purge, "get_client", _fake_get_client(env))

                    transition_tenant_status(
                        client.tenant_id, TenantStatus.DELETED, actor_user_id=owner.id
                    )
                    transition_tenant_status(
                        client.tenant_id, TenantStatus.PURGING, actor_user_id=owner.id
                    )
                    # `purge_tenant()` is a *synchronous* entrypoint, called
                    # only ever from trusted sync tooling -- and
                    # `AutomationDataPurgeParticipant` bridges into its own
                    # Temporal termination call with `asyncio.run()`
                    # (product/automation/purge.py's own module docstring).
                    # `asyncio.run()` cannot be called from a thread that
                    # already has a running loop, so this test must invoke it
                    # exactly the way production does: off the event loop,
                    # on a plain worker thread.
                    await asyncio.to_thread(
                        purge_tenant, client.tenant_id, actor_user_id=owner.id, registry=registry
                    )

                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    description = await _await_temporal_status(
                        handle, (WorkflowExecutionStatus.TERMINATED,)
                    )
                    assert description.status == WorkflowExecutionStatus.TERMINATED

                    # The run is unreachable afterwards. Which of the two
                    # rejections fires is itself defense in depth, and
                    # `AutomationAccessDeniedError` is the *stronger* of
                    # the two: `purge_tenant()` removes this tenant's own
                    # RBAC rows as well, so `require()` now denies the
                    # read before any durable-run lookup even happens. If
                    # a grant somehow survived, the row is gone and the
                    # lookup raises `AutomationReferenceNotFoundError`
                    # instead. Either outcome proves the run cannot be
                    # observed; neither can be bypassed.
                    unreachable = (AutomationAccessDeniedError, AutomationReferenceNotFoundError)
                    with pytest.raises(unreachable):
                        runs.get_run(owner.id, client.tenant_id, run_view.id)
                    # "purged tenant cannot resume a waiting workflow":
                    # the same rejection applies to the signal path, so no
                    # future business activity can be driven either.
                    with pytest.raises(unreachable):
                        await runs.signal_run(
                            owner.id,
                            client.tenant_id,
                            run_view.id,
                            event_type="crm.contact.created",
                            payload={},
                        )
            finally:
                monkeypatch.undo()

        asyncio.run(_run())
    finally:
        # The *client* tenant's automation/CRM rows are already purged,
        # but `purge_tenant()` does not delete the `core.tenants` row
        # itself -- and that row still references the agency tenant as its
        # parent (`tenants_parent_id_fkey`), whose own membership rows
        # still reference `owner`. Both tenants must therefore still be
        # torn down leaf-to-root before the user can be deleted;
        # cleanup_tenant_tree() is itself idempotent against already-empty
        # tables.
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- PRIVACY / HISTORY -----------------------------------------------------


def test_workflow_history_contains_only_bounded_synthetic_context() -> None:
    """A *real* CRM contact, carrying real PII (email, phone, names), is
    the subject of this run -- and only its `contact_id` is ever passed
    into the workflow. The activity fetches everything else from Product
    state after authorizing, inside the activity, so none of that PII can
    reach Temporal's own history."""
    from product.crm.contacts import create_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        secret_email = f"privacy-probe-{uuid.uuid4().hex[:8]}@example.invalid"
        secret_phone = "+15550111999"
        secret_last_name = f"Lastname{uuid.uuid4().hex[:8]}"
        contact = create_contact(
            owner.id,
            client.tenant_id,
            first_name="Privacy",
            last_name=secret_last_name,
            email=secret_email,
            phone=secret_phone,
        )
        steps = [_action_step("s1", title="privacy-check", next_step_key=None)]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner.id,
                        client.tenant_id,
                        workflow.id,
                        context={"contact_id": str(contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    await handle.result()
                    history = await handle.fetch_history()
                    return history
            finally:
                monkeypatch.undo()

        history = asyncio.run(_run())
        # Every payload in this run's history is one of: the bounded
        # workflow/activity input this test itself constructed (the
        # contact *id*, the "privacy-check" title string), or this
        # activity's own bounded {"task_id": ...} result -- never the
        # full CRM record behind that id. This is a structural check
        # (nothing here *could* put more into history than what this test
        # itself passed in) -- not a claim that history is encrypted or
        # access-controlled beyond that (`client.py`'s own "Privacy /
        # history" section, Phase 10.3 infrastructure spike, restated for
        # production).
        raw = str(history)
        assert "privacy-check" in raw  # the bounded synthetic input, expected to appear
        assert str(contact.id) in raw  # the bounded identifier, expected to appear
        assert secret_email not in raw
        assert secret_phone not in raw
        assert secret_last_name not in raw
        assert "notes" not in raw.lower()
        assert "phone" not in raw.lower()
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
