"""End-to-end trigger -> condition -> action execution (docs/ROADMAP.md
Phase 10.2). Real disposable Postgres. Marked `integration`, excluded
from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from core.audit_log import list as list_audit_log
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.automation.dispatcher import MAX_AUTOMATION_DEPTH
from product.automation.models import RUN_STATUS_FAILED, RUN_STATUS_SKIPPED, RUN_STATUS_SUCCESS
from product.automation.workflows import create_workflow, list_workflow_runs
from product.crm.contacts import create_contact, get_contact
from product.crm.opportunities import change_stage, create_opportunity, get_opportunity
from product.crm.pipelines import create_pipeline, create_stage

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_trigger_fires_action_end_to_end() -> None:
    """`crm.contact.created` -> `create_task` -- a real task is created,
    and the run is recorded as success."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Task on new contact",
            trigger_type="crm.contact.created",
            action_type="create_task",
            action_config={"title": "Follow up"},
        )
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")

        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 1
        assert runs[0].status == RUN_STATUS_SUCCESS

        from product.crm.activities import TaskView, list_activities

        activities = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        assert any(isinstance(a, TaskView) and a.title == "Follow up" for a in activities)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_paused_workflow_never_fires() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        from product.automation.workflows import set_workflow_status

        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Paused",
            trigger_type="crm.contact.created",
            action_type="create_task",
            action_config={"title": "Should never run"},
        )
        set_workflow_status(owner.id, client.tenant_id, workflow.id, status="paused")
        create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")

        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert runs == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_condition_gates_execution() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline = create_pipeline(owner.id, client.tenant_id, name="Sales")
        won_stage = create_stage(owner.id, client.tenant_id, pipeline.id, name="Won", position=1)
        lead_stage = create_stage(owner.id, client.tenant_id, pipeline.id, name="Lead", position=0)
        opportunity = create_opportunity(
            owner.id,
            client.tenant_id,
            name="Deal",
            pipeline_id=pipeline.id,
            stage_id=lead_stage.id,
        )
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Notify on win",
            trigger_type="crm.opportunity.stage_changed",
            conditions=[{"field": "to_stage_id", "op": "eq", "value": str(won_stage.id)}],
            action_type="create_task",
            action_config={"title": "Celebrate"},
        )

        # Move to a DIFFERENT stage first -- condition does not match.
        other_stage = create_stage(
            owner.id, client.tenant_id, pipeline.id, name="Qualified", position=2
        )
        change_stage(owner.id, client.tenant_id, opportunity.id, other_stage.id)
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 1
        assert runs[0].status == RUN_STATUS_SKIPPED

        # Now move to the won stage -- condition matches.
        change_stage(owner.id, client.tenant_id, opportunity.id, won_stage.id)
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 2
        assert any(r.status == RUN_STATUS_SUCCESS for r in runs)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_move_opportunity_action_does_not_recursively_retrigger() -> None:
    """Adversarial: a workflow whose own action re-publishes the exact
    event type it is subscribed to (`move_opportunity` calls
    `change_stage()`, which republishes `crm.opportunity.stage_changed`)
    must not chain-trigger a second execution of itself or any other
    workflow -- `MAX_AUTOMATION_DEPTH` structurally prevents it."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline = create_pipeline(owner.id, client.tenant_id, name="Sales")
        stage_a = create_stage(owner.id, client.tenant_id, pipeline.id, name="A", position=0)
        stage_b = create_stage(owner.id, client.tenant_id, pipeline.id, name="B", position=1)
        opportunity = create_opportunity(
            owner.id, client.tenant_id, name="Deal", pipeline_id=pipeline.id, stage_id=stage_a.id
        )
        # This workflow's own action moves the opportunity to stage_b,
        # which republishes crm.opportunity.stage_changed -- if the
        # recursion guard did not exist, this would trigger itself again
        # (and again, unboundedly).
        create_workflow(
            owner.id,
            client.tenant_id,
            name="Self-triggering",
            trigger_type="crm.opportunity.stage_changed",
            action_type="move_opportunity",
            action_config={"to_stage_id": str(stage_b.id)},
        )
        assert MAX_AUTOMATION_DEPTH == 1  # this test's own assumption, made explicit

        change_stage(owner.id, client.tenant_id, opportunity.id, stage_a.id)

        final = get_opportunity(owner.id, client.tenant_id, opportunity.id)
        assert final.stage_id == stage_b.id  # the one, intended move happened

        audit_entries = list_audit_log(
            client.tenant_id,
            resource_type="automation.workflow",
            resource_id="crm.opportunity.stage_changed",
        )
        assert any(e.action == "automation.trigger.max_depth_exceeded" for e in audit_entries)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_action_failure_does_not_propagate_to_the_original_caller() -> None:
    """A workflow's own action failure must never turn an ordinary
    `create_contact()` call into an error for the caller who triggered
    it."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_workflow(
            owner.id,
            client.tenant_id,
            name="Broken action",
            trigger_type="crm.contact.created",
            # move_opportunity on a contact.created trigger has no
            # opportunity_id in the payload -- guaranteed to fail at
            # execution time, with no network dependency.
            action_type="move_opportunity",
            action_config={"to_stage_id": str(uuid.uuid4())},
        )
        # Must not raise, even though the configured action will fail.
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        assert contact.first_name == "A"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_action_failure_recorded_as_failed_run_and_audited() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Move to unknown stage",
            trigger_type="crm.contact.created",
            action_type="move_opportunity",  # contact.created payload has no opportunity_id
            action_config={"to_stage_id": str(uuid.uuid4())},
        )
        create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")

        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 1
        assert runs[0].status == RUN_STATUS_FAILED
        assert runs[0].error

        entries = list_audit_log(
            client.tenant_id, resource_type="automation.workflow", resource_id=str(workflow.id)
        )
        assert any(e.outcome == "failure" for e in entries)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_workflow_cannot_exceed_creators_own_revoked_permissions() -> None:
    """The core adversarial test docs/ROADMAP.md Phase 10.2's own
    Checkpoint calls out explicitly: once the creator's own access is
    revoked, the automation must fail at the exact same authorization
    boundary the creator would hit acting directly -- never succeed
    anyway on cached/assumed permissions."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Rename on create",
            trigger_type="crm.contact.created",
            action_type="update_contact",
            action_config={"first_name": "Renamed"},
        )
        first_contact = create_contact(
            owner.id, client.tenant_id, first_name="Original", last_name="One"
        )
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert runs[0].status == RUN_STATUS_SUCCESS
        updated = get_contact(owner.id, client.tenant_id, first_contact.id)
        assert updated.first_name == "Renamed"

        # Revoke the creator's own crm.contact:update access.
        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource="crm.contact",
            action="update",
        )

        create_contact(owner.id, client.tenant_id, first_name="Second", last_name="Two")
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 2
        latest = sorted(runs, key=lambda r: r.created_at)[-1]
        assert latest.status == RUN_STATUS_FAILED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_triggers_each_create_exactly_one_run() -> None:
    """Two threads each create a contact concurrently -- the same
    workflow fires for each, and each gets its own, distinct
    `WorkflowRun` (never merged, never double-counted, never lost)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Concurrent",
            trigger_type="crm.contact.created",
            action_type="create_task",
            action_config={"title": "Follow up"},
        )

        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _worker(n: int) -> None:
            try:
                barrier.wait(timeout=5)
                create_contact(owner.id, client.tenant_id, first_name=f"P{n}", last_name="X")
            except Exception as exc:  # pragma: no cover -- surfaced via errors list
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 2
        assert all(r.status == RUN_STATUS_SUCCESS for r in runs)
        assert len({r.trigger_dedup_key for r in runs}) == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
