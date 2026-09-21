"""Review recording and lookup (docs/ROADMAP.md Phase 12.1/12.2).

Every mutating/read function authorizes via
`product.reputation.permissions.require()` first, then the actual database
access, then `core.audit_log.record()` for mutations -- metadata carries
only identifiers, never the review's own author name or body text.

**`record_review()` is a manual, authenticated write only** -- there is no
automatic provider sync in this phase (`product/reputation/providers.py`'s
own module docstring: Phase 12.2 is deliberately deferred). `provider`
therefore only ever accepts `'manual'` today; the column and its
`CheckConstraint` already accommodate a future provider name so that a
later Phase 12.2 adapter needs no schema migration to add rows with a real
provider value, only a widened `CheckConstraint` -- see this module's own
future-seam note at `_validate_provider()`.

**Linking a request**: `review_request_id`, if supplied, must reference a
review request in `sent` status belonging to the same tenant -- moves that
request to `fulfilled` (`product/reputation/review_requests.py`'s own
module docstring on the state machine). A request already `cancelled`/
`failed`/`fulfilled` cannot be linked again -- `ReputationValidationError`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.foundation.events import Event, publish
from product.reputation.errors import (
    ReputationConflictError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import (
    MAX_AUTHOR_NAME_LENGTH,
    MAX_REVIEW_BODY_LENGTH,
    PROVIDER_MANUAL,
    REQUEST_STATUS_FULFILLED,
    REQUEST_STATUS_SENT,
    REVIEW_STATUS_NEW,
    Review,
    ReviewRequest,
)
from product.reputation.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.reputation.permissions import REVIEW_RESOURCE, require

REVIEW_RECEIVED_EVENT_TYPE = "reputation.review.received"
REVIEW_RECEIVED_EVENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReviewView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    review_request_id: uuid.UUID | None
    provider: str
    external_review_id: str | None
    rating: int
    author_name: str
    body: str | None
    status: str
    received_at: datetime
    recorded_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _to_view(row: Review) -> ReviewView:
    return ReviewView(
        id=row.id,
        tenant_id=row.tenant_id,
        review_request_id=row.review_request_id,
        provider=row.provider,
        external_review_id=row.external_review_id,
        rating=row.rating,
        author_name=row.author_name,
        body=row.body,
        status=row.status,
        received_at=row.received_at,
        recorded_by_user_id=row.recorded_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_provider(provider: str) -> str:
    # Only 'manual' exists until a real Phase 12.2 adapter is built
    # (module docstring) -- this function is the one place that check
    # lives, so widening it later is a one-line change plus the matching
    # migration to widen `ck_reputation_reviews_provider`.
    if provider != PROVIDER_MANUAL:
        raise ReputationValidationError(f"provider must be {PROVIDER_MANUAL!r} in this phase.")
    return provider


def _validate_rating(rating: int) -> int:
    if not isinstance(rating, int) or isinstance(rating, bool) or not (1 <= rating <= 5):
        raise ReputationValidationError("rating must be an integer between 1 and 5.")
    return rating


def _validate_author_name(author_name: str) -> str:
    if not isinstance(author_name, str) or not author_name.strip():
        raise ReputationValidationError("author_name must not be empty.")
    if len(author_name) > MAX_AUTHOR_NAME_LENGTH:
        raise ReputationValidationError(f"author_name exceeds {MAX_AUTHOR_NAME_LENGTH} characters.")
    return author_name


def _validate_body(body: str | None) -> str | None:
    if body is None:
        return None
    if len(body) > MAX_REVIEW_BODY_LENGTH:
        raise ReputationValidationError(f"body exceeds {MAX_REVIEW_BODY_LENGTH} characters.")
    return body


def record_review(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    rating: int,
    author_name: str,
    body: str | None = None,
    provider: str = PROVIDER_MANUAL,
    review_request_id: uuid.UUID | None = None,
    received_at: datetime | None = None,
) -> ReviewView:
    require(actor_user_id, tenant_id, resource=REVIEW_RESOURCE, action="create")
    validated_provider = _validate_provider(provider)
    validated_rating = _validate_rating(rating)
    validated_author_name = _validate_author_name(author_name)
    validated_body = _validate_body(body)

    review_id = uuid.uuid4()
    with tenant_session_scope(tenant_id) as session:
        if review_request_id is not None:
            request_row = session.get(ReviewRequest, review_request_id)
            if request_row is None or request_row.tenant_id != tenant_id:
                raise ReputationReferenceNotFoundError("review_request", review_request_id)
            if request_row.status != REQUEST_STATUS_SENT:
                raise ReputationValidationError(
                    "cannot link a review to a request in status "
                    f"{request_row.status!r} (must be 'sent')."
                )
            request_row.status = REQUEST_STATUS_FULFILLED
            request_row.fulfilled_at = datetime.now(UTC)

        try:
            session.add(
                Review(
                    id=review_id,
                    tenant_id=tenant_id,
                    review_request_id=review_request_id,
                    provider=validated_provider,
                    external_review_id=None,
                    rating=validated_rating,
                    author_name=validated_author_name,
                    body=validated_body,
                    status=REVIEW_STATUS_NEW,
                    received_at=received_at or datetime.now(UTC),
                    recorded_by_user_id=actor_user_id,
                )
            )
            session.flush()
        except IntegrityError as exc:
            raise ReputationConflictError("review_request_id", str(review_request_id)) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Review, review_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="reputation.review.recorded",
        resource_type="reputation.review",
        resource_id=str(review_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"provider": validated_provider, "rating": str(validated_rating)},
    )
    publish(
        Event(
            type=REVIEW_RECEIVED_EVENT_TYPE,
            version=REVIEW_RECEIVED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "review_id": str(review_id),
                "provider": validated_provider,
                "rating": validated_rating,
            },
        )
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, review_id: uuid.UUID) -> Review:
    row = session.get(Review, review_id)
    if row is None or row.tenant_id != tenant_id:
        raise ReputationReferenceNotFoundError("review", review_id)
    return row


def get_review(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, review_id: uuid.UUID) -> ReviewView:
    require(actor_user_id, tenant_id, resource=REVIEW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, review_id)
        session.expunge(row)
    return _to_view(row)


def list_reviews(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ReviewView]:
    require(actor_user_id, tenant_id, resource=REVIEW_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Review)
                .where(Review.tenant_id == tenant_id)
                .order_by(Review.received_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


__all__ = [
    "REVIEW_RECEIVED_EVENT_TYPE",
    "ReviewView",
    "get_review",
    "list_reviews",
    "record_review",
]
