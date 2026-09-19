"""Conversation thread CRUD and assignment (docs/ROADMAP.md Phase 5.1,
5.5).

`create_thread()` requires a real, same-tenant `contact_id` -- the
roadmap's own 5.1 Objective ("linked to a CRM contact"), enforced here at
the service layer even though the underlying column is nullable (see
`product/conversations/models.py`'s own module docstring for why: the
column must support `ON DELETE SET NULL` so a later contact deletion
unlinks rather than destroys history, but a *newly created* thread always
starts linked).

`assign_thread()` validates the assignee actually holds a real
`TenantMembership` at `tenant_id` (`core.identity.get_membership()`)
before assigning -- assigning to a syntactically-valid-but-unrelated
`user_id` must fail; this is the real IDOR-adjacent check, not a
formality (mirrors `product/crm/contacts.py::_require_company_in_tenant()`'s
own "defense in depth" reasoning, though here there is no composite FK to
fall back on since `core.users` is a global table -- this check is the
only enforcement, so it must be unconditional).

**`contact_id` validation deliberately does NOT read `crm.contacts`
directly** -- `product.conversations` importing `product.crm.models`
(or any `product.crm` symbol) would violate the independence contract
`docs/ARCHITECTURE.md` section 2.2 enforces between sibling product
modules (the identical rule that already forced `product/crm
/event_handlers.py` to react to `product.agency`'s events instead of
importing it). Unlike the CRM module's own `company_id` check (which
CAN afford a same-module pre-check since `crm.companies` and
`crm.contacts` are both owned by `product.crm` itself), a cross-module
reference has no such option. `create_thread()` therefore relies
entirely on `conversations.threads.contact_id`'s own composite
`ForeignKeyConstraint` (`product/conversations/models.py`) as BOTH the
tenant-isolation guarantee AND the "does this contact actually exist"
check -- a real, structural, database-enforced validation, not a weaker
substitute for one. An `IntegrityError` from that constraint (unknown or
cross-tenant `contact_id`) is caught here and re-raised as the identical
`ConversationReferenceNotFoundError` a pre-check would have raised, so
callers see no behavioral difference.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.identity import get_membership
from infra.db import IntegrityError, select, tenant_session_scope

from product.conversations.errors import (
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.models import VALID_CHANNELS, ConversationThread
from product.conversations.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.conversations.permissions import THREAD_RESOURCE, require


@dataclass(frozen=True, slots=True)
class ThreadView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID | None
    channel: str
    assigned_to_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: ConversationThread) -> ThreadView:
    return ThreadView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        channel=row.channel,
        assigned_to_user_id=row.assigned_to_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_valid_channel(channel: str) -> None:
    if channel not in VALID_CHANNELS:
        raise ConversationValidationError(
            f"channel must be one of {VALID_CHANNELS}, got: {channel!r}"
        )


def create_thread(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, contact_id: uuid.UUID, channel: str
) -> ThreadView:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="create")
    _require_valid_channel(channel)
    try:
        with tenant_session_scope(tenant_id) as session:
            row = ConversationThread(tenant_id=tenant_id, contact_id=contact_id, channel=channel)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        # The composite FK on contact_id is the real validation -- see
        # module docstring. An unknown or cross-tenant contact_id lands
        # here, never as an opaque 500.
        raise ConversationReferenceNotFoundError("contact", contact_id) from exc
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.thread.create",
        resource_type="conversations.thread",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"channel": channel},
    )
    return _to_view(row)


def get_thread(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, thread_id: uuid.UUID) -> ThreadView:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(ConversationThread, thread_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("thread", thread_id)
        session.expunge(row)
    return _to_view(row)


def list_threads(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ThreadView]:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(ConversationThread)
                .where(ConversationThread.tenant_id == tenant_id)
                .order_by(ConversationThread.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_thread(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    *,
    channel: str | None = None,
) -> ThreadView:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="update")
    if channel is not None:
        _require_valid_channel(channel)
    with tenant_session_scope(tenant_id) as session:
        row = session.get(ConversationThread, thread_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("thread", thread_id)
        if channel is not None:
            row.channel = channel
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.thread.update",
        resource_type="conversations.thread",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def assign_thread(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    assignee_user_id: uuid.UUID,
) -> ThreadView:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="update")
    # The real IDOR-adjacent check -- see module docstring. There is no
    # composite FK to fall back on (core.users is a global table), so
    # this check is the only enforcement and must be unconditional.
    if get_membership(tenant_id, assignee_user_id) is None:
        raise ConversationReferenceNotFoundError("assignee", assignee_user_id)
    with tenant_session_scope(tenant_id) as session:
        row = session.get(ConversationThread, thread_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("thread", thread_id)
        row.assigned_to_user_id = assignee_user_id
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.thread.assign",
        resource_type="conversations.thread",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"assigned_to_user_id": str(assignee_user_id)},
    )
    return _to_view(row)


def delete_thread(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(ConversationThread, thread_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("thread", thread_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.thread.delete",
        resource_type="conversations.thread",
        resource_id=str(thread_id),
        outcome=AuditOutcome.SUCCESS,
    )
