"""Phase 10.3 durable-execution infrastructure spike -- end-to-end proof
against a real (not mocked) ephemeral Temporal test server, via the
SDK's own official in-process test environment
(`temporalio.testing.WorkflowEnvironment`).

Marked `temporal`, excluded from the default `pytest` run (mirrors the
existing `integration` marker's own exclusion, `pyproject.toml`) --
these tests need outbound network access the first time they run in a
given environment, to download the Temporal CLI dev-server/test-server
binary the SDK manages itself (cached under a temp directory afterward,
same pattern this repository already uses for a real disposable
Postgres container in `scripts/check-integration.sh`, just a different
kind of "real disposable service"). Run explicitly:

    pytest tests/automation/durable -m temporal

No `pytest-asyncio` dependency added for this (this phase's own minimum-
dependency policy) -- each test is a plain, synchronous `def` that runs
its own body via `asyncio.run(...)`, exactly `tests/automation/durable
/test_bounded_input_unit.py`'s own precedent, extended to a full
`async with` body here.

No product database, no `core.rbac`, no real tenant is involved anywhere
in this file -- every identifier is synthetic (module docstring,
`product/automation/durable/client.py`'s own "Privacy / history"
section).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from product.automation.durable.activities import probe_activity
from product.automation.durable.client import (
    list_workflows_for_tenant,
    submit_probe_workflow,
    terminate_workflows_for_tenant,
)
from product.automation.durable.workflows import ProbeWorkflow, ProbeWorkflowInput
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

pytestmark = pytest.mark.temporal

_TASK_QUEUE = "automation-durable-spike-test"


def _synthetic_tenant_id() -> str:
    return f"spike-tenant-{uuid.uuid4().hex[:8]}"


def test_worker_connects_and_registers_workflow_and_activity() -> None:
    """Spike outcomes 1-2: the engine starts (the test environment's own
    ephemeral server), and a Product worker can connect to it and
    register this phase's one workflow/activity pair with no error."""

    async def _run() -> None:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            worker = Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[ProbeWorkflow],
                activities=[probe_activity],
            )
            # Successful entry/exit of the Worker's own async context
            # manager -- with no exception -- is itself the proof: it
            # connects to the (real, ephemeral) server and registers
            # `ProbeWorkflow`/`probe_activity` on `_TASK_QUEUE`.
            # `worker.is_running` is deliberately not asserted here: it
            # reflects an internal poll-loop state that is not
            # guaranteed true at the exact instant `__aenter__` returns
            # (confirmed empirically -- asserting it here was flaky).
            async with worker:
                pass

    asyncio.run(_run())


def test_trivial_workflow_and_activity_execute_end_to_end() -> None:
    """Spike outcomes 3-4: a trivial workflow can be submitted, a
    trivial activity executes (twice, per `ProbeWorkflow.run`'s own
    two-activity-plus-durable-sleep shape), and the result is bounded
    and deterministic. The inter-activity sleep is real Temporal-managed
    durable-timer time; the time-skipping test environment fast-forwards
    through it automatically once the result is awaited, so this test
    does not itself wait 8 real seconds."""
    tenant_id = _synthetic_tenant_id()

    async def _run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[ProbeWorkflow],
                activities=[probe_activity],
            ):
                handle = await submit_probe_workflow(
                    env.client,
                    tenant_id=tenant_id,
                    resource_id="spike-resource-1",
                    task_queue=_TASK_QUEUE,
                )
                return await handle.result()

    result = asyncio.run(_run())

    assert result.first.echoed_tenant_id == tenant_id
    assert result.first.echoed_resource_id == "spike-resource-1"
    assert result.second.echoed_tenant_id == tenant_id
    assert result.second.echoed_resource_id == "spike-resource-1"


def test_workflow_history_replays_deterministically() -> None:
    """Spike required test 5 ("deterministic workflow behavior"), proved
    the way Temporal itself proves it: fetch the completed execution's
    real event history and replay it through `temporalio.worker.Replayer`
    -- the SDK's own authoritative determinism check, which re-executes
    the workflow's code against the recorded history and raises if the
    code's actual behavior diverges from what was recorded (a real
    non-determinism bug, not merely "ran twice and got the same
    answer")."""
    tenant_id = _synthetic_tenant_id()

    async def _run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[ProbeWorkflow],
                activities=[probe_activity],
            ):
                handle = await submit_probe_workflow(
                    env.client,
                    tenant_id=tenant_id,
                    resource_id="spike-resource-1",
                    task_queue=_TASK_QUEUE,
                )
                await handle.result()
                return await handle.fetch_history()

    history = asyncio.run(_run())

    replayer = Replayer(workflows=[ProbeWorkflow])
    # Raises on a genuine non-determinism failure (raise_on_replay_failure
    # defaults to True) -- a clean return is the proof.
    asyncio.run(replayer.replay_workflow(history))


async def _poll_until(predicate, *, attempts: int = 20, delay_seconds: float = 0.5):
    """Temporal's List Workflow Executions API (used by
    `list_workflows_for_tenant()`) is backed by an eventually-consistent
    visibility store even on a single-node dev server -- a workflow that
    was just started is not guaranteed to be immediately visible to a
    list query. Polls briefly rather than asserting on the first
    attempt; this is test-only accommodation for that documented
    characteristic, not something `client.py`'s own production code
    needs to account for (a real purge participant naturally runs some
    time after the triggering purge transition, not in the same instant
    a workflow was started)."""
    last_result = None
    for _ in range(attempts):
        last_result = await predicate()
        if last_result:
            return last_result
        await asyncio.sleep(delay_seconds)
    return last_result


def test_tenant_scoped_list_and_terminate_interface() -> None:
    """The tenant-lifecycle/purge interface boundary this spike proves
    out (not a full purge-participant integration -- `client.py`'s own
    docstring): workflows for two different synthetic tenants are
    distinguishable by `list_workflows_for_tenant()`, and
    `terminate_workflows_for_tenant()` terminates only the target
    tenant's own still-running execution, leaving the other tenant's
    completed execution alone.

    Uses `WorkflowEnvironment.start_local()` (a real dev-server process,
    not the time-skipping test server) -- confirmed empirically that the
    time-skipping server does not implement `ListWorkflowExecutions`
    ("Method ... unimplemented"), so this specific test needs the full
    dev server. Real time elapses here (this workflow's own
    `_INTER_ACTIVITY_SLEEP_SECONDS` durable sleep is not skipped), so
    this test takes several real seconds -- acceptable for an explicit,
    `temporal`-marked spike test."""
    tenant_a = _synthetic_tenant_id()
    tenant_b = _synthetic_tenant_id()

    async def _run():
        async with await WorkflowEnvironment.start_local() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[ProbeWorkflow],
                activities=[probe_activity],
            ):
                handle_a = await submit_probe_workflow(
                    env.client, tenant_id=tenant_a, resource_id="r-a", task_queue=_TASK_QUEUE
                )
                await handle_a.result()

                # Tenant B's own workflow, started but deliberately never
                # awaited to completion within this block, so it is
                # still RUNNING (mid its own durable sleep) when
                # terminate_workflows_for_tenant() is called below.
                await env.client.start_workflow(
                    ProbeWorkflow.run,
                    ProbeWorkflowInput(tenant_id=tenant_b, resource_id="r-b"),
                    id=f"automation-durable-probe:{tenant_b}:{uuid.uuid4().hex}",
                    task_queue=_TASK_QUEUE,
                )

                a_matches = await _poll_until(
                    lambda: list_workflows_for_tenant(env.client, tenant_id=tenant_a)
                )
                b_matches = await _poll_until(
                    lambda: list_workflows_for_tenant(env.client, tenant_id=tenant_b)
                )
                assert a_matches and len(a_matches) == 1
                assert b_matches and len(b_matches) == 1
                assert a_matches[0].id != b_matches[0].id

                terminated_count = await terminate_workflows_for_tenant(
                    env.client, tenant_id=tenant_b, reason="test: purge-interface proof"
                )
                assert terminated_count == 1

                b_description = await b_matches[0].describe()
                assert b_description.status == WorkflowExecutionStatus.TERMINATED

                a_description = await a_matches[0].describe()
                assert a_description.status == WorkflowExecutionStatus.COMPLETED

    asyncio.run(_run())
