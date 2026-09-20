"""The "scheduled" trigger's on-demand sweep (docs/ROADMAP.md Phase
10.2). Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.automation.scheduled import sweep_scheduled_workflows
from product.automation.workflows import SCHEDULED_TRIGGER_TYPE, create_workflow, list_workflow_runs

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_scheduled_workflow_fires_on_first_sweep() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        # send_email (unlike create_task) needs no CRM entity attachment
        # from the trigger payload -- the "scheduled" trigger's own
        # payload is always empty ({}), matching a real "daily digest
        # email" workflow shape.
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Daily digest",
            trigger_type=SCHEDULED_TRIGGER_TYPE,
            trigger_config={"interval_hours": 24},
            action_type="send_email",
            action_config={
                "to": "owner@example.com",
                "subject": "Daily digest",
                "body": "Here is your daily digest.",
            },
        )
        result = sweep_scheduled_workflows(owner.id, client.tenant_id)
        assert result.swept_count == 1
        assert workflow.id in result.fired_workflow_ids

        # This test is about the sweep's own due-detection firing the
        # workflow exactly once -- not about send_email's own delivery
        # outcome (no real SMTP is configured in this test environment;
        # product/automation/dispatcher.py::test_action_failure_recorded_*
        # already covers the action-failure-is-recorded-and-audited path
        # directly).
        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_scheduled_workflow_not_due_again_before_interval_elapses() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_workflow(
            owner.id,
            client.tenant_id,
            name="Daily digest",
            trigger_type=SCHEDULED_TRIGGER_TYPE,
            trigger_config={"interval_hours": 24},
            action_type="send_email",
            action_config={
                "to": "owner@example.com",
                "subject": "Daily digest",
                "body": "Here is your daily digest.",
            },
        )
        now = datetime.now(UTC)
        first = sweep_scheduled_workflows(owner.id, client.tenant_id, now=now)
        assert first.swept_count == 1

        soon = now + timedelta(hours=1)
        second = sweep_scheduled_workflows(owner.id, client.tenant_id, now=soon)
        assert second.swept_count == 0

        later = now + timedelta(hours=25)
        third = sweep_scheduled_workflows(owner.id, client.tenant_id, now=later)
        assert third.swept_count == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_sweep_requires_read_permission() -> None:
    from product.automation.errors import AutomationAccessDeniedError

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(AutomationAccessDeniedError):
            sweep_scheduled_workflows(unrelated.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)
