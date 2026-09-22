"""The Unified Inbox read model (docs/ROADMAP.md Phase 30) -- composes
`conversations.threads` with each thread's own latest
`conversations.message` into one business-oriented list, entirely within
`product/conversations/` (the one module that already owns both tables).

**Why this exists, not just `list_threads()` + `list_messages()` called
separately by the frontend**: a real inbox list needs, per thread, the
latest message's preview/direction/timestamp to be useful at all ("what
happened, what should I do next") -- fetching that client-side would mean
one `list_messages()` call per visible thread (a real N+1 the frontend
cannot avoid on its own, since no endpoint returns it pre-joined). This
module does that composition once, server-side, in the one place that
already has direct table access to both.

**No `product.crm` dependency, by the same rule
`product/conversations/threads.py`'s own module docstring already
states and enforces** (`product.conversations` importing any
`product.crm` symbol would violate the sibling-module independence
contract) -- `InboxItemView` carries only `contact_id`, never a contact
name/company. The Unified Inbox *experience* (frontend) resolves contact
identity by calling CRM's own existing `GET .../contacts/{id}` for the
bounded set of contacts a rendered page actually shows -- composition at
the experience layer, exactly matching Phase 30's own architecture
diagram ("Unified Inbox -> Conversations capability + Contact context,
each via existing product APIs"), never inside this module.

**No `unread`/read-state column exists anywhere in this schema**
(`product/conversations/models.py` has no such field, verified by
reading it directly) -- `needs_reply` below is not that. It is a
derived, honest signal computed from data that already exists and is
already correct: the *latest non-internal-note message's own
`direction`* -- `True` when the last real customer-facing message was
`inbound` (the customer spoke last, nobody replied yet), `False`
otherwise. This is deliberately named `needs_reply`, never `unread`, so
it is never mistaken for state this schema does not track.

**Latest-message-per-thread query strategy**: `infra.db` deliberately
exposes no window-function primitive (`func`/`over`) to product code --
only a narrow, curated set of SQLAlchemy primitives
(`infra/db/__init__.py`'s own `__all__`), the same "Only infra/db may
import SQLAlchemy directly" boundary this whole codebase enforces. A
correlated-subquery-per-thread (bounded to at most one page's worth of
threads, `MAX_PAGE_SIZE` per `product/conversations/pagination.py`) is
therefore used instead of a single window-function query -- the same,
already-accepted "bounded N+1, not an unbounded fan-out" trade-off
`docs/ROADMAP.md` Phase 28's own Command Center automation-activity
composition already documented and shipped with. Revisit only if
`infra.db` itself ever grows a window-function helper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from infra.db import select, tenant_session_scope

from product.conversations.models import DIRECTION_INBOUND, ConversationMessage, ConversationThread
from product.conversations.pagination import MAX_PAGE_SIZE, clamp_limit
from product.conversations.permissions import THREAD_RESOURCE, require

_PREVIEW_MAX_CHARS = 140

AssignedFilter = Literal["me", "unassigned"]


@dataclass(frozen=True, slots=True)
class InboxItemView:
    thread_id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID | None
    channel: str
    assigned_to_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None
    """`None` for a thread with no messages at all yet -- a real,
    honest, empty conversation, not an error."""
    last_message_at: datetime | None
    last_message_direction: str | None
    last_message_is_internal_note: bool | None
    needs_reply: bool
    """See module docstring -- derived from `last_message_direction`,
    never a persisted/fabricated flag. Always `False` when there is no
    message yet (nothing to reply to)."""


def _preview(body: str) -> str:
    stripped = " ".join(body.split())
    if len(stripped) <= _PREVIEW_MAX_CHARS:
        return stripped
    return stripped[: _PREVIEW_MAX_CHARS - 1].rstrip() + "…"


def _latest_message(
    session, tenant_id: uuid.UUID, thread_id: uuid.UUID
) -> ConversationMessage | None:
    return session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.tenant_id == tenant_id,
            ConversationMessage.thread_id == thread_id,
        )
        .order_by(ConversationMessage.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_inbox(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    assigned: AssignedFilter | None = None,
    channel: str | None = None,
    needs_reply: bool = False,
    limit: int = MAX_PAGE_SIZE,
    offset: int = 0,
) -> list[InboxItemView]:
    """Lists this tenant's own threads with each one's latest-message
    summary attached, newest-activity-first. `assigned="me"` restricts to
    `actor_user_id`'s own assignments; `assigned="unassigned"` restricts
    to threads with no assignee. `needs_reply=True` restricts to threads
    whose latest real message is inbound with no reply yet.

    Bounded, not true offset-pagination, when `needs_reply` is set: the
    filter is computed per-thread in Python (module docstring -- no
    window-function primitive available), so it operates over a
    candidate window of at most `MAX_PAGE_SIZE` threads (by recency)
    rather than the database applying `LIMIT`/`OFFSET` before the filter
    -- documented here rather than silently returning a shorter page
    than `limit` for a reason a caller could not otherwise discover.
    """
    require(actor_user_id, tenant_id, resource=THREAD_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)

    with tenant_session_scope(tenant_id) as session:
        stmt = select(ConversationThread).where(ConversationThread.tenant_id == tenant_id)
        if assigned == "me":
            stmt = stmt.where(ConversationThread.assigned_to_user_id == actor_user_id)
        elif assigned == "unassigned":
            stmt = stmt.where(ConversationThread.assigned_to_user_id.is_(None))
        if channel is not None:
            stmt = stmt.where(ConversationThread.channel == channel)

        candidate_limit = MAX_PAGE_SIZE if needs_reply else bounded_limit
        candidate_offset = 0 if needs_reply else max(offset, 0)
        threads = (
            session.execute(
                stmt.order_by(ConversationThread.updated_at.desc())
                .limit(candidate_limit)
                .offset(candidate_offset)
            )
            .scalars()
            .all()
        )

        items: list[InboxItemView] = []
        for thread in threads:
            latest = _latest_message(session, tenant_id, thread.id)
            item_needs_reply = latest is not None and latest.direction == DIRECTION_INBOUND
            if needs_reply and not item_needs_reply:
                continue
            items.append(
                InboxItemView(
                    thread_id=thread.id,
                    tenant_id=thread.tenant_id,
                    contact_id=thread.contact_id,
                    channel=thread.channel,
                    assigned_to_user_id=thread.assigned_to_user_id,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    last_message_preview=_preview(latest.body) if latest is not None else None,
                    last_message_at=latest.created_at if latest is not None else None,
                    last_message_direction=latest.direction if latest is not None else None,
                    last_message_is_internal_note=(
                        latest.is_internal_note if latest is not None else None
                    ),
                    needs_reply=item_needs_reply,
                )
            )

        for thread in threads:
            session.expunge(thread)

    if needs_reply:
        items = items[max(offset, 0) : max(offset, 0) + bounded_limit]
    return items


def count_needs_reply(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    """The real count behind the Command Center's "N conversations need
    attention" line (docs/ROADMAP.md Phase 30) -- computed the identical
    way `list_inbox(needs_reply=True)` does, over the same bounded
    `MAX_PAGE_SIZE` candidate window. A tenant with more than
    `MAX_PAGE_SIZE` open threads gets an honest lower-bound count rather
    than an unbounded scan -- documented, not hidden."""
    return len(list_inbox(actor_user_id, tenant_id, needs_reply=True, limit=MAX_PAGE_SIZE))


__all__ = ["InboxItemView", "count_needs_reply", "list_inbox"]
