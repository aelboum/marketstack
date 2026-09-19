"""Tasks, notes, and the merged activity timeline (docs/ROADMAP.md
Phase 4.3).

**Permission mapping, per `docs/ROADMAP.md` Phase 4's own consolidated
design** (see `product/crm/permissions.py`'s module docstring): a
task/note attached to a contact/company/opportunity is gated by the SAME
permission as updating (for create/update/delete) or reading (for
read/list) the entity it attaches to -- there is no separate
`crm.task`/`crm.note` permission resource. `_entity_resource()` below
resolves which of `CONTACT_RESOURCE`/`COMPANY_RESOURCE`/
`OPPORTUNITY_RESOURCE` applies for a given attachment.

**Exactly-one-entity validation happens twice, deliberately**: once here
(a clean `CrmValidationError`/`CrmReferenceNotFoundError` before any
database write), and once, unconditionally, by `crm.tasks`/`crm.notes`'s
own `CHECK` constraint (`product/crm/models.py`) -- the constraint is
what actually makes this impossible to violate, the service-layer check
is only for a better error than a raw `IntegrityError`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import Company, Contact, Note, Opportunity, Task
from product.crm.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.crm.permissions import (
    COMPANY_RESOURCE,
    CONTACT_RESOURCE,
    OPPORTUNITY_RESOURCE,
    require,
)


@dataclass(frozen=True, slots=True)
class _Attachment:
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None


def _entity_resource(attachment: _Attachment) -> str:
    set_count = sum(
        1
        for value in (attachment.contact_id, attachment.company_id, attachment.opportunity_id)
        if value is not None
    )
    if set_count != 1:
        raise CrmValidationError(
            f"exactly one of contact_id/company_id/opportunity_id must be set, got {set_count}."
        )
    if attachment.contact_id is not None:
        return CONTACT_RESOURCE
    if attachment.company_id is not None:
        return COMPANY_RESOURCE
    return OPPORTUNITY_RESOURCE


def _require_attachment_target_in_tenant(
    session, tenant_id: uuid.UUID, attachment: _Attachment
) -> None:
    if attachment.contact_id is not None:
        row = session.get(Contact, attachment.contact_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("contact", attachment.contact_id)
    elif attachment.company_id is not None:
        row = session.get(Company, attachment.company_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("company", attachment.company_id)
    else:
        assert attachment.opportunity_id is not None
        row = session.get(Opportunity, attachment.opportunity_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("opportunity", attachment.opportunity_id)


# --- Tasks -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    title: str
    description: str | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    kind: str = "task"


def _task_view(row: Task) -> TaskView:
    return TaskView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        company_id=row.company_id,
        opportunity_id=row.opportunity_id,
        title=row.title,
        description=row.description,
        due_at=row.due_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_task(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    title: str,
    description: str | None = None,
    due_at: datetime | None = None,
    contact_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> TaskView:
    attachment = _Attachment(contact_id, company_id, opportunity_id)
    resource = _entity_resource(attachment)
    require(actor_user_id, tenant_id, resource=resource, action="update")
    with tenant_session_scope(tenant_id) as session:
        _require_attachment_target_in_tenant(session, tenant_id, attachment)
        row = Task(
            tenant_id=tenant_id,
            contact_id=contact_id,
            company_id=company_id,
            opportunity_id=opportunity_id,
            title=title,
            description=description,
            due_at=due_at,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.task.create",
        resource_type="crm.task",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _task_view(row)


def complete_task(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, task_id: uuid.UUID, *, completed_at: datetime
) -> TaskView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Task, task_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("task", task_id)
        resource = _entity_resource(_Attachment(row.contact_id, row.company_id, row.opportunity_id))
        require(actor_user_id, tenant_id, resource=resource, action="update")
        row.completed_at = completed_at
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.task.complete",
        resource_type="crm.task",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _task_view(row)


def delete_task(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, task_id: uuid.UUID) -> None:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Task, task_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("task", task_id)
        resource = _entity_resource(_Attachment(row.contact_id, row.company_id, row.opportunity_id))
        require(actor_user_id, tenant_id, resource=resource, action="update")
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.task.delete",
        resource_type="crm.task",
        resource_id=str(task_id),
        outcome=AuditOutcome.SUCCESS,
    )


# --- Notes ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoteView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    body: str
    created_at: datetime
    updated_at: datetime
    kind: str = "note"


def _note_view(row: Note) -> NoteView:
    return NoteView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        company_id=row.company_id,
        opportunity_id=row.opportunity_id,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_note(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    body: str,
    contact_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> NoteView:
    attachment = _Attachment(contact_id, company_id, opportunity_id)
    resource = _entity_resource(attachment)
    require(actor_user_id, tenant_id, resource=resource, action="update")
    with tenant_session_scope(tenant_id) as session:
        _require_attachment_target_in_tenant(session, tenant_id, attachment)
        row = Note(
            tenant_id=tenant_id,
            contact_id=contact_id,
            company_id=company_id,
            opportunity_id=opportunity_id,
            body=body,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.note.create",
        resource_type="crm.note",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _note_view(row)


def delete_note(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, note_id: uuid.UUID) -> None:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Note, note_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("note", note_id)
        resource = _entity_resource(_Attachment(row.contact_id, row.company_id, row.opportunity_id))
        require(actor_user_id, tenant_id, resource=resource, action="update")
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.note.delete",
        resource_type="crm.note",
        resource_id=str(note_id),
        outcome=AuditOutcome.SUCCESS,
    )


# --- Merged timeline -------------------------------------------------------


def list_activities(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[TaskView | NoteView]:
    """Tasks and notes attached to the one named entity, merged and
    sorted newest-first by `created_at`, paginated. Exactly one of
    `contact_id`/`company_id`/`opportunity_id` must be given."""
    attachment = _Attachment(contact_id, company_id, opportunity_id)
    resource = _entity_resource(attachment)
    require(actor_user_id, tenant_id, resource=resource, action="read")
    bounded_limit = clamp_limit(limit)

    filters_task = [Task.tenant_id == tenant_id]
    filters_note = [Note.tenant_id == tenant_id]
    if contact_id is not None:
        filters_task.append(Task.contact_id == contact_id)
        filters_note.append(Note.contact_id == contact_id)
    elif company_id is not None:
        filters_task.append(Task.company_id == company_id)
        filters_note.append(Note.company_id == company_id)
    else:
        filters_task.append(Task.opportunity_id == opportunity_id)
        filters_note.append(Note.opportunity_id == opportunity_id)

    with tenant_session_scope(tenant_id) as session:
        tasks = session.execute(select(Task).where(*filters_task)).scalars().all()
        notes = session.execute(select(Note).where(*filters_note)).scalars().all()
        for row in (*tasks, *notes):
            session.expunge(row)

    merged: list[TaskView | NoteView] = [
        *(_task_view(t) for t in tasks),
        *(_note_view(n) for n in notes),
    ]
    merged.sort(key=lambda item: item.created_at, reverse=True)
    start = max(offset, 0)
    return merged[start : start + bounded_limit]
