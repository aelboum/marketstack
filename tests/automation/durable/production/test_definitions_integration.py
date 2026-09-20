"""Workflow/version definition CRUD against real disposable Postgres
(docs/ROADMAP.md Phase 10.3's own required "WORKFLOW DEFINITION" test
group, the integration half). Marked `integration`, excluded from the
default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.automation.durable import definitions
from product.automation.durable.models import (
    STATUS_PAUSED,
    VERSION_STATUS_DRAFT,
    VERSION_STATUS_PUBLISHED,
)
from product.automation.errors import AutomationReferenceNotFoundError, AutomationValidationError

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _steps() -> list:
    return [
        {
            "step_key": "s1",
            "type": "action",
            "action_type": "create_task",
            "action_config": {"title": "x"},
            "next_step_key": None,
        }
    ]


def test_create_workflow_creates_draft_v1() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow, version = definitions.create_workflow(
            owner.id, client.tenant_id, name="Onboarding", start_step_key="s1", steps=_steps()
        )
        assert workflow.name == "Onboarding"
        assert version.version_number == 1
        assert version.status == VERSION_STATUS_DRAFT
        assert workflow.current_published_version_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_publish_version_makes_it_immutable() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow, version = definitions.create_workflow(
            owner.id, client.tenant_id, name="Onboarding", start_step_key="s1", steps=_steps()
        )
        published = definitions.publish_version(owner.id, client.tenant_id, workflow.id, version.id)
        assert published.status == VERSION_STATUS_PUBLISHED
        assert published.published_at is not None

        refreshed_workflow = definitions.get_workflow(owner.id, client.tenant_id, workflow.id)
        assert refreshed_workflow.current_published_version_id == version.id

        with pytest.raises(AutomationValidationError):
            definitions.update_draft_version(
                owner.id,
                client.tenant_id,
                workflow.id,
                version.id,
                start_step_key="s1",
                steps=_steps(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_changing_a_published_workflow_requires_a_new_version() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow, version = definitions.create_workflow(
            owner.id, client.tenant_id, name="Onboarding", start_step_key="s1", steps=_steps()
        )
        definitions.publish_version(owner.id, client.tenant_id, workflow.id, version.id)

        new_steps = [
            {
                "step_key": "s1",
                "type": "action",
                "action_type": "create_task",
                "action_config": {"title": "changed"},
                "next_step_key": None,
            }
        ]
        draft2 = definitions.create_draft_version(
            owner.id, client.tenant_id, workflow.id, start_step_key="s1", steps=new_steps
        )
        assert draft2.version_number == 2
        assert draft2.status == VERSION_STATUS_DRAFT
        assert draft2.id != version.id

        # The original published version is untouched.
        original = definitions.get_version(owner.id, client.tenant_id, workflow.id, version.id)
        assert original.steps == _steps()

        # The workflow's own current_published_version_id has NOT moved
        # to the new draft -- only publish_version() can do that.
        refreshed_workflow = definitions.get_workflow(owner.id, client.tenant_id, workflow.id)
        assert refreshed_workflow.current_published_version_id == version.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_disabling_workflow_does_not_invalidate_historical_runs_metadata() -> None:
    """Disabling/archiving must not touch already-published version
    rows -- this phase's own "deleting/archiving a workflow must not
    invalidate historical runs" requirement, checked at the definition
    layer (the run layer's own equivalent test lives in
    test_execution_temporal.py)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow, version = definitions.create_workflow(
            owner.id, client.tenant_id, name="Onboarding", start_step_key="s1", steps=_steps()
        )
        definitions.publish_version(owner.id, client.tenant_id, workflow.id, version.id)
        definitions.set_workflow_status(
            owner.id, client.tenant_id, workflow.id, status=STATUS_PAUSED
        )
        still_there = definitions.get_version(owner.id, client.tenant_id, workflow.id, version.id)
        assert still_there.status == VERSION_STATUS_PUBLISHED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_workflow_lookup_is_non_enumerating() -> None:
    owner_a = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    owner_b = make_user()
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        workflow, _version = definitions.create_workflow(
            owner_a.id, client_a.tenant_id, name="A-only", start_step_key="s1", steps=_steps()
        )
        with pytest.raises(AutomationReferenceNotFoundError):
            definitions.get_workflow(owner_b.id, client_b.tenant_id, workflow.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
