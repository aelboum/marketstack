"""Review request lifecycle (docs/ROADMAP.md Phase 12.1).

Every mutating/read function authorizes via
`product.reputation.permissions.require()` first, then the actual database
access, then `core.audit_log.record()` for mutations -- metadata carries
only identifiers, never a contact's email address or the request's own
message body (mirrors `product/websites/websites.py`'s own bounded/
identifier-only metadata discipline).

**Contact resolution reuses `product.crm.contacts.get_contact()`**
(`docs/ADR/0010-reputation-depends-on-crm.md`) -- this module never
constructs or reads a `crm.contacts` row directly. `get_contact()` is
itself RBAC-gated on `crm.contact:read`, so `create_review_request()`
requires the actor to independently hold both this module's own
`reputation.review_request:create` and CRM's `crm.contact:read` --
deliberate defense in depth, not a bypass (ADR-0010's own Decision
section).

**Send is synchronous, and the row is persisted regardless of outcome** --
a deliberate divergence from `product/conversations/email_sending.py
::send_email_message()`'s own "no message row on failure" precedent: that
module's `Message` represents a thing that was sent, so a failed send
correctly produces no row; this module's `ReviewRequest` represents an
*attempt to reach a customer*, and Phase 12.1's own objective is
explicitly "track its status" -- a failed attempt is itself a fact worth
tracking (`status='failed'`, `failure_reason` set), not one to discard.

**Lifecycle**: `pending` (never observed by a caller -- set only for the
instant between insert and the synchronous send outcome) -> `sent` |
`failed`. From `sent`, a caller may `cancel_review_request()` ->
`cancelled`, or `product.reputation.reviews.record_review()` may link a
new `Review` to this request -> `fulfilled`
(`product/reputation/reviews.py`'s own module docstring). No other
transition is valid; `ReputationValidationError` on an invalid one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.email import EmailMessage, get_email_config, send_email
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError
from core.email.provider import EmailProvider
from infra.db import select, tenant_session_scope

from product.crm.contacts import get_contact
from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError
from product.foundation.events import Event, publish
from product.reputation.errors import (
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import (
    REQUEST_CHANNEL_EMAIL,
    REQUEST_CHANNELS,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_FAILED,
    REQUEST_STATUS_PENDING,
    REQUEST_STATUS_SENT,
    ReviewRequest,
)
from product.reputation.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.reputation.permissions import REVIEW_REQUEST_RESOURCE, require

REQUEST_CREATED_EVENT_TYPE = "reputation.review_request.created"
REQUEST_CREATED_EVENT_VERSION = 1
REQUEST_SENT_EVENT_TYPE = "reputation.review_request.sent"
REQUEST_SENT_EVENT_VERSION = 1
REQUEST_FAILED_EVENT_TYPE = "reputation.review_request.failed"
REQUEST_FAILED_EVENT_VERSION = 1

_DEFAULT_SUBJECT = "We'd love your feedback"


@dataclass(frozen=True, slots=True)
class ReviewRequestView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    channel: str
    status: str
    failure_reason: str | None
    requested_by_user_id: uuid.UUID
    sent_at: datetime | None
    cancelled_at: datetime | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: ReviewRequest) -> ReviewRequestView:
    return ReviewRequestView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        channel=row.channel,
        status=row.status,
        failure_reason=row.failure_reason,
        requested_by_user_id=row.requested_by_user_id,
        sent_at=row.sent_at,
        cancelled_at=row.cancelled_at,
        fulfilled_at=row.fulfilled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_channel(channel: str) -> str:
    if channel not in REQUEST_CHANNELS:
        raise ReputationValidationError(f"channel must be one of {REQUEST_CHANNELS}.")
    return channel


def _validate_message(message: str | None) -> str | None:
    if message is None:
        return None
    if not isinstance(message, str) or not message.strip():
        raise ReputationValidationError("message must not be empty when provided.")
    return message


def create_review_request(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    *,
    channel: str = REQUEST_CHANNEL_EMAIL,
    message: str | None = None,
    email_provider: EmailProvider | None = None,
) -> ReviewRequestView:
    """Creates the request row, then attempts to send it synchronously.
    The row is persisted regardless of send outcome (module docstring).
    `email_provider` is test-injection only, mirroring
    `product/conversations/email_sending.py::send_email_message()`'s
    identical parameter."""
    require(actor_user_id, tenant_id, resource=REVIEW_REQUEST_RESOURCE, action="create")
    validated_channel = _validate_channel(channel)
    validated_message = _validate_message(message)

    try:
        contact = get_contact(actor_user_id, tenant_id, contact_id)
    except CrmReferenceNotFoundError:
        raise ReputationReferenceNotFoundError("contact", contact_id) from None
    except CrmAccessDeniedError:
        # The actor holds reputation.review_request:create but not
        # crm.contact:read -- surfaced as this module's own not-found
        # shape, never CRM's own exception type crossing the module
        # boundary (docs/ARCHITECTURE.md section 2.2: a module's own
        # errors are its own published surface, not another module's).
        raise ReputationReferenceNotFoundError("contact", contact_id) from None

    if contact.email is None:
        raise ReputationValidationError("contact has no email address on file.")

    request_id = uuid.uuid4()
    with tenant_session_scope(tenant_id) as session:
        session.add(
            ReviewRequest(
                id=request_id,
                tenant_id=tenant_id,
                contact_id=contact_id,
                channel=validated_channel,
                status=REQUEST_STATUS_PENDING,
                requested_by_user_id=actor_user_id,
            )
        )
        session.flush()

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="reputation.review_request.created",
        resource_type="reputation.review_request",
        resource_id=str(request_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"contact_id": str(contact_id)},
    )
    publish(
        Event(
            type=REQUEST_CREATED_EVENT_TYPE,
            version=REQUEST_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"review_request_id": str(request_id), "contact_id": str(contact_id)},
        )
    )

    body = validated_message or (
        "Hi, we'd really appreciate it if you could take a moment to leave us a review."
    )
    config = get_email_config()
    send_failure_reason: str | None = None
    if not config.default_sender:
        send_failure_reason = "EMAIL_DEFAULT_SENDER is not set."
    else:
        try:
            send_email(
                EmailMessage(
                    sender=config.default_sender,
                    to=(contact.email,),
                    subject=_DEFAULT_SUBJECT,
                    text_body=body,
                ),
                provider=email_provider,
            )
        except (EmailConfigurationError, EmailProviderError, InvalidEmailAddressError) as exc:
            send_failure_reason = str(exc)

    with tenant_session_scope(tenant_id) as session:
        row = session.get(ReviewRequest, request_id)
        assert row is not None
        if send_failure_reason is None:
            row.status = REQUEST_STATUS_SENT
            row.sent_at = datetime.now(UTC)
        else:
            row.status = REQUEST_STATUS_FAILED
            row.failure_reason = send_failure_reason[:500]
        session.flush()
        session.refresh(row)
        session.expunge(row)

    if send_failure_reason is None:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="reputation.review_request.sent",
            resource_type="reputation.review_request",
            resource_id=str(request_id),
            outcome=AuditOutcome.SUCCESS,
        )
        publish(
            Event(
                type=REQUEST_SENT_EVENT_TYPE,
                version=REQUEST_SENT_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"review_request_id": str(request_id)},
            )
        )
    else:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="reputation.review_request.failed",
            resource_type="reputation.review_request",
            resource_id=str(request_id),
            outcome=AuditOutcome.FAILURE,
        )
        publish(
            Event(
                type=REQUEST_FAILED_EVENT_TYPE,
                version=REQUEST_FAILED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"review_request_id": str(request_id)},
            )
        )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, request_id: uuid.UUID) -> ReviewRequest:
    row = session.get(ReviewRequest, request_id)
    if row is None or row.tenant_id != tenant_id:
        raise ReputationReferenceNotFoundError("review_request", request_id)
    return row


def get_review_request(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> ReviewRequestView:
    require(actor_user_id, tenant_id, resource=REVIEW_REQUEST_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, request_id)
        session.expunge(row)
    return _to_view(row)


def list_review_requests(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ReviewRequestView]:
    require(actor_user_id, tenant_id, resource=REVIEW_REQUEST_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        query = select(ReviewRequest).where(ReviewRequest.tenant_id == tenant_id)
        if contact_id is not None:
            query = query.where(ReviewRequest.contact_id == contact_id)
        rows = (
            session.execute(
                query.order_by(ReviewRequest.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def cancel_review_request(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> ReviewRequestView:
    require(actor_user_id, tenant_id, resource=REVIEW_REQUEST_RESOURCE, action="cancel")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, request_id)
        if row.status not in (REQUEST_STATUS_PENDING, REQUEST_STATUS_SENT):
            raise ReputationValidationError(
                f"cannot cancel a review request in status {row.status!r}."
            )
        row.status = REQUEST_STATUS_CANCELLED
        row.cancelled_at = datetime.now(UTC)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="reputation.review_request.cancelled",
        resource_type="reputation.review_request",
        resource_id=str(request_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


__all__ = [
    "REQUEST_CREATED_EVENT_TYPE",
    "REQUEST_FAILED_EVENT_TYPE",
    "REQUEST_SENT_EVENT_TYPE",
    "ReviewRequestView",
    "cancel_review_request",
    "create_review_request",
    "get_review_request",
    "list_review_requests",
]
