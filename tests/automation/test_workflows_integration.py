"""Workflow CRUD, isolation/authorization (docs/ROADMAP.md Phase 10.2).
Real disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.automation.errors import (
    AutomationAccessDeniedError,
    AutomationReferenceNotFoundError,
    AutomationValidationError,
)
from product.automation.workflows import (
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    set_workflow_status,
)

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_workflow_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Notify on new contact",
            trigger_type="crm.contact.created",
            action_type="create_task",
            action_config={"title": "Follow up with new contact"},
        )
        assert workflow.status == "active"

        fetched = get_workflow(owner.id, client.tenant_id, workflow.id)
        assert fetched.id == workflow.id

        listed = list_workflows(owner.id, client.tenant_id)
        assert any(w.id == workflow.id for w in listed)

        paused = set_workflow_status(owner.id, client.tenant_id, workflow.id, status="paused")
        assert paused.status == "paused"

        delete_workflow(owner.id, client.tenant_id, workflow.id)
        with pytest.raises(AutomationReferenceNotFoundError):
            get_workflow(owner.id, client.tenant_id, workflow.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_workflow() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(AutomationAccessDeniedError):
            create_workflow(
                unrelated.id,
                client.tenant_id,
                name="X",
                trigger_type="crm.contact.created",
                action_type="create_task",
                action_config={"title": "x"},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_workflows_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="X",
            trigger_type="crm.contact.created",
            action_type="create_task",
            action_config={"title": "x"},
        )
        with pytest.raises(AutomationReferenceNotFoundError):
            get_workflow(other_owner.id, other_client.tenant_id, workflow.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_invalid_trigger_type_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AutomationValidationError):
            create_workflow(
                owner.id,
                client.tenant_id,
                name="X",
                trigger_type="not.a.real.trigger",
                action_type="create_task",
                action_config={"title": "x"},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_action_config_rejected_at_create_time() -> None:
    """A malformed workflow definition is rejected when created, never
    discovered the first time it tries to fire."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AutomationValidationError):
            create_workflow(
                owner.id,
                client.tenant_id,
                name="X",
                trigger_type="crm.contact.created",
                action_type="create_task",
                action_config={},  # missing required "title"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_oversized_action_config_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AutomationValidationError):
            create_workflow(
                owner.id,
                client.tenant_id,
                name="X",
                trigger_type="crm.contact.created",
                action_type="create_task",
                action_config={"title": "x" * 20_000},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
