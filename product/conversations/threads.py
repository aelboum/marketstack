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

**`create_thread()`'s own `contact_id` validation deliberately does NOT
read `crm.contacts` directly** -- this is unchanged by Phase 30 below.
Unlike the CRM module's own `company_id` check (which CAN afford a
same-module pre-check since `crm.companies` and `crm.contacts` are both
owned by `product.crm` itself), a cross-module reference has no such
option for an *authenticated, caller-supplied* `contact_id`.
`create_thread()` therefore relies entirely on
`conversations.threads.contact_id`'s own composite `ForeignKeyConstraint`
(`product/conversations/models.py`) as BOTH the tenant-isolation guarantee
AND the "does this contact actually exist" check -- a real, structural,
database-enforced validation, not a weaker substitute for one. An
`IntegrityError` from that constraint (unknown or cross-tenant
`contact_id`) is caught here and re-raised as the identical
`ConversationReferenceNotFoundError` a pre-check would have raised, so
callers see no behavioral difference.

**Phase 30 (docs/ROADMAP.md "Unified Inbox") adds the one narrow
exception**: `create_thread_from_trusted_inbound()` below imports
`product.crm.contacts`' own published
`create_or_reuse_contact_from_trusted_source_by_phone()` function (never
`product.crm.models`, never any other CRM symbol) -- a deliberate,
ADR-authorized edge (`docs/ADR/0019-conversations-depends-on-crm.md`),
not a reopening of the independence rule above. It exists because that
function's own `contact_id` is resolved *inside this module*, from a
trusted inbound phone identifier, not supplied by an already-authenticated
caller the way `create_thread()`'s is -- there is no pre-existing
`contact_id` for the database FK to validate until after the CRM call
returns one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.identity import get_membership
from infra.db import IntegrityError, acquire_tenant_advisory_lock, select, tenant_session_scope

from product.conversations.errors import (
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.models import (
    CHANNEL_CALL,
    CHANNEL_SMS,
    CHANNEL_WHATSAPP,
    VALID_CHANNELS,
    ConversationThread,
)
from product.conversations.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.conversations.permissions import THREAD_RESOURCE, require
from product.crm.contacts import create_or_reuse_contact_from_trusted_source_by_phone

# Phase 30: the subset of VALID_CHANNELS a trusted inbound phone identifier
# can plausibly arrive on -- deliberately excludes CHANNEL_EMAIL (no phone
# identifier) and CHANNEL_CHAT (already an authenticated, in-app channel,
# never a trusted-inbound one).
_TRUSTED_INBOUND_PHONE_CHANNELS = (CHANNEL_SMS, CHANNEL_WHATSAPP, CHANNEL_CALL)


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


def create_thread_from_trusted_inbound(
    tenant_id: uuid.UUID, *, channel: str, from_phone: str, source: str
) -> ThreadView:
    """Phase 30 (docs/ROADMAP.md "Unified Inbox"), authorized by
    `docs/ADR/0019-conversations-depends-on-crm.md`. The one trusted
    inbound entry point for phone-keyed identity resolution + auto-created
    threads -- infrastructure for a future inbound SMS/WhatsApp/call
    provider integration, not that integration itself (no vendor code, no
    webhook route, lives here).

    **Deliberately a separate function from `create_thread()` above, never
    a variant of it** -- `create_thread()`'s existing authenticated
    contract (`actor_user_id`, `require()`, a caller-supplied `contact_id`
    that must already exist) is completely unchanged by this addition; no
    existing caller of `create_thread()` is affected. This function has no
    `actor_user_id` and calls no `product.conversations.permissions
    .require()`, mirroring `product.crm.contacts
    .create_or_update_contact_from_trusted_source()`'s own established
    "trusts its caller" shape for the identical reason: there is no
    authenticated actor on an inbound phone/SMS/WhatsApp delivery path.
    This must never be reached from any authenticated route.

    **Channel is restricted to the trusted-inbound-phone subset**
    (`sms`, `whatsapp`, `call`) of `VALID_CHANNELS` -- not `email` (no
    phone identifier to correlate on) and not `chat` (already an
    authenticated, in-app channel; never a trusted-inbound one).

    **Resolution order**: `tenant_id` + normalized `from_phone` resolve or
    create a CRM contact via `product.crm.contacts
    .create_or_reuse_contact_from_trusted_source_by_phone()` (see that
    function's own docstring for the full ADR-0018/ADR-0019 trust
    contract: correlation only, never authentication, never mutates a
    matched contact's trusted fields, a newly-created contact is
    explicitly unverified). The resolved `contact.id` + `channel` then
    resolve or create exactly one `ConversationThread` -- the most
    recently created open thread for that `(tenant_id, contact_id,
    channel)` combination is reused; if none exists, a new thread is
    created and linked. Two separate transactions (the CRM call opens its
    own `tenant_session_scope()`), mirroring `product/websites/leads.py`'s
    own disclosed "cannot be composed into one atomic transaction" shape
    for the identical reason -- both steps are independently idempotent
    under retry (see below), so a retry that repeats the contact
    resolution step is harmless.

    **Concurrency**: `conversations.threads` carries no unique constraint
    on `(tenant_id, contact_id, channel)`, so a bare select-then-create
    here would race under concurrent duplicate inbound delivery (two
    workers processing the same inbound event). Serialized with the same
    `infra.db.acquire_tenant_advisory_lock()` primitive the CRM function
    above uses, keyed on `(tenant_id, contact_id, channel)`, held for this
    function's own transaction only -- a second, concurrent caller blocks
    until the first commits, then re-reads and finds the thread the first
    caller just created."""
    if channel not in _TRUSTED_INBOUND_PHONE_CHANNELS:
        raise ConversationValidationError(
            f"channel must be one of {_TRUSTED_INBOUND_PHONE_CHANNELS} for a trusted inbound "
            f"phone delivery, got: {channel!r}"
        )
    contact = create_or_reuse_contact_from_trusted_source_by_phone(
        tenant_id, phone=from_phone, source=source
    )
    with tenant_session_scope(tenant_id) as session:
        lock_key = f"conversations.thread_by_contact_channel.{tenant_id}.{contact.id}.{channel}"
        acquire_tenant_advisory_lock(session, tenant_id, lock_key)
        existing = (
            session.execute(
                select(ConversationThread)
                .where(
                    ConversationThread.tenant_id == tenant_id,
                    ConversationThread.contact_id == contact.id,
                    ConversationThread.channel == channel,
                )
                .order_by(ConversationThread.created_at.desc())
                .limit(1)
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            session.expunge(existing)
            row = existing
            action = "conversations.thread.reuse_from_trusted_inbound"
        else:
            row = ConversationThread(tenant_id=tenant_id, contact_id=contact.id, channel=channel)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            action = "conversations.thread.create_from_trusted_inbound"
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action=action,
        resource_type="conversations.thread",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"channel": channel, "source": source},
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
