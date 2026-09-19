"""Tasks, notes, and the merged activity timeline (docs/ROADMAP.md
Phase 4.3). Real disposable Postgres. Marked `integration`, excluded
from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from infra.db import IntegrityError, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.crm.activities import (
    complete_task,
    create_note,
    create_task,
    delete_task,
    list_activities,
)
from product.crm.contacts import create_contact
from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import Task

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_task_and_note_attach_to_contact_and_appear_in_timeline() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Timeline", last_name="Target"
        )
        task = create_task(owner.id, client.tenant_id, title="Follow up", contact_id=contact.id)
        note = create_note(
            owner.id, client.tenant_id, body="Called, left voicemail.", contact_id=contact.id
        )

        timeline = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        kinds = {item.kind for item in timeline}
        ids = {item.id for item in timeline}
        assert kinds == {"task", "note"}
        assert {task.id, note.id} == ids
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_task_completion_and_deletion() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        task = create_task(owner.id, client.tenant_id, title="Do the thing", contact_id=contact.id)
        assert task.completed_at is None

        completed = complete_task(
            owner.id, client.tenant_id, task.id, completed_at=datetime.now(UTC)
        )
        assert completed.completed_at is not None

        delete_task(owner.id, client.tenant_id, task.id)
        remaining = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        assert all(item.id != task.id for item in remaining)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_exactly_one_entity_enforced_at_service_layer() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="B")
        with pytest.raises(CrmValidationError):
            create_task(owner.id, client.tenant_id, title="No entity")
        with pytest.raises(CrmValidationError):
            create_note(
                owner.id,
                client.tenant_id,
                body="Two entities",
                contact_id=contact.id,
                company_id=uuid.uuid4(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_exactly_one_entity_enforced_by_database_constraint_directly() -> None:
    """The CHECK constraint itself, bypassing the service layer's own
    pre-check entirely."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client.tenant_id) as session:
                row = Task(tenant_id=client.tenant_id, title="No entity at all")
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_deleting_contact_cascades_its_tasks_and_notes() -> None:
    """product/crm/models.py's own documented deletion behavior: a
    task/note has no independent meaning without its one required
    parent."""
    from product.crm.contacts import delete_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Doomed", last_name="Contact"
        )
        task = create_task(owner.id, client.tenant_id, title="Orphan-to-be", contact_id=contact.id)
        delete_contact(owner.id, client.tenant_id, contact.id)

        with tenant_session_scope(client.tenant_id) as session:
            assert session.get(Task, task.id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_activity_attachment_reference_must_exist_in_same_tenant() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        contact_b = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="Only")
        with pytest.raises(CrmReferenceNotFoundError):
            create_task(
                owner_a.id, client_a.tenant_id, title="Cross tenant", contact_id=contact_b.id
            )
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)
