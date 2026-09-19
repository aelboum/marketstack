"""Suppression list (docs/ROADMAP.md Phase 6.1's own "unsubscribe/
suppression list honored before every send -- a hard gate" security
requirement).

**Opt-out model, not opt-in** -- a deliberate reading of the roadmap's own
words ("unsubscribe/suppression list"), not an invented legal stance: a
contact is presumed eligible to receive a campaign on a given channel
unless an explicit `MarketingSuppression` row exists for that
`(tenant_id, contact_id, channel)`. This is the CAN-SPAM-style opt-out
shape, not a GDPR-style opt-in-required shape -- the roadmap's own
Security Considerations line names "CAN-SPAM/GDPR obligations" together
without picking one, and `docs/ROADMAP.md`'s own instruction is explicit:
"flagged here as an architecture requirement, not a legal claim." Which
model is actually correct for this product's Dutch/EU market is a real
question for Phase 18's dedicated compliance review, not decided here --
this module only implements the mechanical hard gate the roadmap's
Security Considerations line requires, honored at both campaign-
enrollment time and send time (see `product/marketing/sending.py`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.marketing.errors import MarketingReferenceNotFoundError, MarketingValidationError
from product.marketing.models import VALID_CHANNELS, VALID_SUPPRESSION_REASONS, MarketingSuppression
from product.marketing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.marketing.permissions import SUPPRESSION_RESOURCE, require


@dataclass(frozen=True, slots=True)
class SuppressionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    channel: str
    reason: str
    created_at: datetime


def _to_view(row: MarketingSuppression) -> SuppressionView:
    return SuppressionView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        channel=row.channel,
        reason=row.reason,
        created_at=row.created_at,
    )


def create_suppression(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    channel: str,
    reason: str,
) -> SuppressionView:
    require(actor_user_id, tenant_id, resource=SUPPRESSION_RESOURCE, action="create")
    if channel not in VALID_CHANNELS:
        raise MarketingValidationError(f"channel must be one of {VALID_CHANNELS}, got: {channel!r}")
    if reason not in VALID_SUPPRESSION_REASONS:
        raise MarketingValidationError(
            f"reason must be one of {VALID_SUPPRESSION_REASONS}, got: {reason!r}"
        )
    with tenant_session_scope(tenant_id) as session:
        row = MarketingSuppression(
            tenant_id=tenant_id, contact_id=contact_id, channel=channel, reason=reason
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.suppression.create",
        resource_type="marketing.suppression",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"contact_id": str(contact_id), "channel": channel, "reason": reason},
    )
    return _to_view(row)


def list_suppressions(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[SuppressionView]:
    require(actor_user_id, tenant_id, resource=SUPPRESSION_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MarketingSuppression)
                .where(MarketingSuppression.tenant_id == tenant_id)
                .order_by(MarketingSuppression.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def delete_suppression(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, suppression_id: uuid.UUID
) -> None:
    """Deleting a suppression re-subscribes the contact -- a more
    consequential, owner-level action than creating one (see
    `product/marketing/event_handlers.py`'s own role-grant reasoning:
    the `member` role gets `create`/`read` but not `delete` on this
    resource)."""
    require(actor_user_id, tenant_id, resource=SUPPRESSION_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingSuppression, suppression_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("suppression", suppression_id)
        contact_id = row.contact_id
        channel = row.channel
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.suppression.delete",
        resource_type="marketing.suppression",
        resource_id=str(suppression_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"contact_id": str(contact_id), "channel": channel},
    )


def is_suppressed(tenant_id: uuid.UUID, contact_id: uuid.UUID, channel: str) -> bool:
    """The hard gate every send path must call -- both at campaign-
    enrollment time (`product/marketing/sending.py::start_campaign_send()`)
    and again at actual send time (the job handler), since a contact can
    unsubscribe *between* those two moments. Deliberately takes no
    `actor_user_id`/permission check of its own -- this is an internal
    gate the send path calls on every recipient's behalf, not a
    caller-facing read operation; the caller (`sending.py`) already holds
    `marketing.campaign` authority for the campaign as a whole."""
    with tenant_session_scope(tenant_id) as session:
        existing = (
            session.execute(
                select(MarketingSuppression).where(
                    MarketingSuppression.tenant_id == tenant_id,
                    MarketingSuppression.contact_id == contact_id,
                    MarketingSuppression.channel == channel,
                )
            )
            .scalars()
            .one_or_none()
        )
    return existing is not None
