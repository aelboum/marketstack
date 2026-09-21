"""The `ai.crm.qualify_lead` Automation action, executed through the real
Phase 10.3 durable Temporal engine (docs/ROADMAP.md Phase 10.4A). Marked
BOTH `integration` and `temporal`, excluded from the default `pytest` run
and from the plain `integration`-only run -- identical discipline to
`test_execution_temporal.py`, whose own `_harness()`/polling-helper
pattern this file duplicates locally rather than importing (that file's
own helpers are private/file-local by the same established convention).

Proves the registry integration survives the real execution path this
phase's own architecture exists to serve: a durable run resolves
`ai.crm.qualify_lead` through Automation's neutral registry, executes it
inside a real Temporal activity dispatched through the production
worker's own `activity_executor` threadpool
(`product/automation/durable/business_activities.py`, unmodified), and
the resulting permanent/transient classification, idempotency, and audit
behaviour all come from the *existing*, unmodified 10.3 machinery --
nothing here is AI-specific at the engine layer.

    pytest tests/automation/durable/production/test_ai_action_execution_temporal.py \\
        -m "integration and temporal"
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import pytest
from control_plane.data_authorization import ProviderEligibilityPolicy
from core.audit_log import list as list_audit_log
from product.action_registry_composition import wire_production_automation_actions
from product.agency.provisioning import provision_agency, provision_client
from product.ai.policy import set_tenant_ai_policy
from product.ai.production import (
    clear_production_llm_provider,
    register_production_llm_provider,
)
from product.ai.provider import FakeLLMProvider, LLMCompletion
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY
from product.automation.durable import definitions, runs
from product.automation.durable.models import (
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from product.automation.durable.production_workflow import (
    PRODUCTION_TASK_QUEUE,
    DurableWorkflow,
)
from product.crm.contacts import create_contact
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.temporal]

_TERMINAL = (RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED)
_PROVIDER_NAME = "durable-test-double"


class _DurableTestDoubleProvider:
    """See `tests/ai/test_automation_action_integration.py`'s own module
    docstring for why a non-"fake"-named delegate is needed to exercise
    `production_tool_registry()`'s real code path."""

    def __init__(self) -> None:
        self._delegate = FakeLLMProvider()

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        inner = self._delegate.complete(
            system_prompt=system_prompt,
            user_content=user_content,
            max_output_chars=max_output_chars,
        )
        return LLMCompletion(text=inner.text, provider_name=self.name)


@pytest.fixture(autouse=True, scope="module")
def _ensure_production_actions_composed() -> None:
    wire_production_automation_actions()


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _approve(owner_id, tenant_id) -> None:
    set_tenant_ai_policy(
        owner_id,
        tenant_id,
        enabled=True,
        approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
        allowed_providers=(_PROVIDER_NAME,),
    )


def _ai_step(step_key: str, *, next_step_key: str | None = None) -> dict:
    return {
        "step_key": step_key,
        "type": "action",
        "action_type": QUALIFY_LEAD_TOOL_KEY,
        "action_config": {},
        "next_step_key": next_step_key,
    }


def _task_step(step_key: str, *, title: str, next_step_key: str | None = None) -> dict:
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
    assert run_view.temporal_workflow_id is not None
    return run_view.temporal_workflow_id


def _fake_get_client(env):
    async def _get_client(config=None):
        return env.client

    return _get_client


@asynccontextmanager
async def _harness(monkeypatch: pytest.MonkeyPatch):
    env = await WorkflowEnvironment.start_time_skipping()
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


def _wait_for_terminal(actor_id, tenant_id, run_id, *, timeout_seconds: float = 20.0):
    import time

    deadline = time.monotonic() + timeout_seconds
    view = runs.get_run(actor_id, tenant_id, run_id)
    while view.status not in _TERMINAL and time.monotonic() < deadline:
        time.sleep(0.1)
        view = runs.get_run(actor_id, tenant_id, run_id)
    return view


@pytest.fixture(autouse=True)
def _production_provider(monkeypatch):
    """Registers a non-test-double-named production provider, and widens
    platform-wide provider eligibility to accept it, test-scope only --
    see `tests/ai/test_automation_action_integration.py`'s own module
    docstring for the full reasoning (identical here: with no override,
    `PLATFORM_PROVIDER_POLICY`'s real `{"fake"}`-only list makes the
    allow path unreachable through the real adapter, which always calls
    `production_tool_registry()`). The monkeypatch mutates a module-level
    global shared across threads in this process, so it applies equally
    to the Temporal worker's own `activity_executor` threads below."""
    widened = ProviderEligibilityPolicy(eligible_providers=frozenset({_PROVIDER_NAME}))
    monkeypatch.setattr("product.ai.policy.PLATFORM_PROVIDER_POLICY", widened)
    monkeypatch.setattr("product.ai.invocation.PLATFORM_PROVIDER_POLICY", widened)
    clear_production_llm_provider()
    register_production_llm_provider(_DurableTestDoubleProvider())
    yield
    clear_production_llm_provider()


# --- execution -----------------------------------------------------------


def test_ai_action_executes_successfully_through_durable_workflow() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="L")
        _approve(owner.id, client.tenant_id)
        workflow, _version = _publish(
            owner.id, client.tenant_id, start_step_key="s1", steps=[_ai_step("s1")]
        )

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
        assert [s.step_key for s in step_views] == ["s1"]
        assert step_views[0].status == "succeeded"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_ai_action_and_create_task_coexist_in_the_same_run() -> None:
    """Regression + no-special-case proof: a single durable run mixing a
    built-in action and the AI action, resolved through the identical
    generic dispatch, back to back."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="L")
        _approve(owner.id, client.tenant_id)
        steps = [
            _task_step("s1", title="before-ai", next_step_key="s2"),
            _ai_step("s2", next_step_key=None),
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
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- failure / recovery / authorization -----------------------------------


def test_ai_action_denied_without_policy_fails_non_retryably_with_audit() -> None:
    """No policy configured -> `WorkflowActionDeniedError` ->
    `business_activities.py`'s own `_PERMANENT_DENIAL_ERRORS` bucket ->
    `ApplicationError(non_retryable=True)` -> the run fails, and the
    `automation.durable_run.authorization_denied` audit event (this
    engine's own required event, unmodified) is recorded -- proves the
    classification, not merely asserts it."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        workflow, _version = _publish(
            owner.id, client.tenant_id, start_step_key="s1", steps=[_ai_step("s1")]
        )

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

        entries = list_audit_log(
            client.tenant_id, resource_type="automation.durable_run", resource_id=str(run_id)
        )
        assert any(e.action == "automation.durable_run.authorization_denied" for e in entries)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_ai_action_revoked_between_wait_and_execution_denies_only_that_step() -> None:
    """The core adversarial shape 10.2/10.3's own equivalent tests already
    require, applied to the AI action: the policy is approved when the
    run starts, then revoked while the run is genuinely paused
    (`wait_for_event`), before the AI step ever executes -- proving
    execution-time authorization, never a decision captured at
    publish/start time."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)
        steps = [
            {
                "step_key": "s1",
                "type": "wait_for_event",
                "event_type": "crm.contact.created",
                "timeout_seconds": 3600,
                "next_step_key": "s2",
                "timeout_step_key": None,
            },
            _ai_step("s2", next_step_key=None),
        ]
        workflow, _version = _publish(owner.id, client.tenant_id, start_step_key="s1", steps=steps)

        async def _run():
            loop = asyncio.get_running_loop()
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

                    deadline = loop.time() + 20.0
                    view = await asyncio.to_thread(
                        runs.get_run, owner.id, client.tenant_id, run_view.id
                    )
                    while view.status != "waiting" and loop.time() < deadline:
                        await asyncio.sleep(0.1)
                        view = await asyncio.to_thread(
                            runs.get_run, owner.id, client.tenant_id, run_view.id
                        )
                    assert view.status == "waiting"

                    # Revoke while paused -- disables the tenant's own
                    # policy entirely, matching the "disabled tenant"
                    # required case, exercised here at execution time.
                    set_tenant_ai_policy(
                        owner.id,
                        client.tenant_id,
                        enabled=False,
                        approved_capabilities=(QUALIFY_LEAD_TOOL_KEY,),
                        allowed_providers=(_PROVIDER_NAME,),
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
        assert by_key["s2"].status == "failed"  # AI step denied at execution time
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_ai_action_cross_tenant_contact_fails_the_step() -> None:
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _approve(owner_a.id, client_a.tenant_id)
        b_contact = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="B")
        workflow, _version = _publish(
            owner_a.id, client_a.tenant_id, start_step_key="s1", steps=[_ai_step("s1")]
        )

        async def _run():
            monkeypatch = pytest.MonkeyPatch()
            try:
                async with _harness(monkeypatch) as env:
                    run_view = await runs.start_run(
                        owner_a.id,
                        client_a.tenant_id,
                        workflow.id,
                        context={"contact_id": str(b_contact.id)},
                    )
                    handle = env.client.get_workflow_handle(_temporal_id(run_view))
                    await handle.result()
                    return run_view.id
            finally:
                monkeypatch.undo()

        run_id = asyncio.run(_run())
        final = _wait_for_terminal(owner_a.id, client_a.tenant_id, run_id)
        assert final.status == RUN_STATUS_FAILED
        step_views = runs.list_run_steps(owner_a.id, client_a.tenant_id, run_id)
        assert step_views[0].status == "failed"
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- idempotency -----------------------------------------------------------


async def _call_activity(fn, arg):
    """Unlike `test_execution_temporal.py`'s own identically-named helper
    (which calls `fn(arg)` directly, fine for every built-in action, none
    of which is itself `async`-anything), this dispatches onto a separate
    thread via `asyncio.to_thread()`. The AI action's own `execute()`
    (`product/ai/automation_action.py`) bridges to async internally with
    its own `asyncio.run()` call, which correctly refuses to run inside a
    thread that already has an event loop running (exactly the hazard
    that adapter's own docstring documents) -- calling `fn(arg)` directly
    from inside this already-running coroutine would trigger precisely
    that. Dispatching onto a thread has no event loop of its own,
    matching the *real* Temporal Worker's own `activity_executor`
    threadpool model even more faithfully than a direct call would."""
    return await asyncio.to_thread(fn, arg)


def test_ai_action_duplicate_activity_invocation_remains_idempotent() -> None:
    """Calls the real activity function directly (bypassing Temporal
    entirely, mirroring `test_execution_temporal.py
    ::test_duplicate_activity_execution_remains_idempotent`'s own
    pattern) twice with the identical `(run_id, step_key)` idempotency
    key -- proves the *existing* `core.idempotency` wrapper
    (`execute_step_action_activity`, unmodified) already covers the AI
    action with no AI-specific idempotency code needed."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        _approve(owner.id, client.tenant_id)

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
            action_type=QUALIFY_LEAD_TOOL_KEY,
            action_config={},
            context={"contact_id": str(contact.id)},
        )

        first = asyncio.run(_call_activity(execute_step_action_activity, step_input))
        second = asyncio.run(_call_activity(execute_step_action_activity, step_input))
        assert first.result == second.result  # the replayed result, not a second real invocation
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
