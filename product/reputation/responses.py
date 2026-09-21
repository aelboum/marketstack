"""Responding to a review (docs/ROADMAP.md Phase 12.3).

Every mutating/read function authorizes via
`product.reputation.permissions.require()` first (the same `REVIEW_RESOURCE`
a `Review` mutation uses -- a response has no independent access boundary
apart from the review it responds to, `product/reputation/permissions.py`'s
own module docstring), then the actual database access, then
`core.audit_log.record()`.

**Posting to the real provider only for a non-`manual` review** -- a
`manual` review (the only kind this phase can produce,
`product/reputation/reviews.py`'s own module docstring) has no external
platform to post to; its response is simply recorded. A future
provider-backed review would need `product.reputation.providers
.resolve_provider()` to return a real adapter -- which it never does in
this phase (`product/reputation/providers.py`'s own module docstring) --
so that path raises `ReputationProviderNotConfiguredError` explicitly
rather than silently recording a response that was never actually posted
anywhere. `provider_client` is test-injection only (mirrors
`product/reputation/review_requests.py::create_review_request()`'s own
`email_provider` parameter), bypassing `resolve_provider()` so tests can
exercise the real-provider code path without one being configured in
production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.foundation.events import Event, publish
from product.reputation.errors import (
    ReputationProviderNotConfiguredError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import (
    MAX_RESPONSE_BODY_LENGTH,
    PROVIDER_MANUAL,
    REVIEW_STATUS_RESPONDED,
    Review,
    ReviewResponse,
)
from product.reputation.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.reputation.permissions import REVIEW_RESOURCE, require
from product.reputation.providers import ReviewProvider, resolve_provider

REVIEW_RESPONDED_EVENT_TYPE = "reputation.review.responded"
REVIEW_RESPONDED_EVENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReviewResponseView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    review_id: uuid.UUID
    body: str
    posted_by_user_id: uuid.UUID
    created_at: datetime


def _to_view(row: ReviewResponse) -> ReviewResponseView:
    return ReviewResponseView(
        id=row.id,
        tenant_id=row.tenant_id,
        review_id=row.review_id,
        body=row.body,
        posted_by_user_id=row.posted_by_user_id,
        created_at=row.created_at,
    )


def _validate_body(body: str) -> str:
    if not isinstance(body, str) or not body.strip():
        raise ReputationValidationError("body must not be empty.")
    if len(body) > MAX_RESPONSE_BODY_LENGTH:
        raise ReputationValidationError(f"body exceeds {MAX_RESPONSE_BODY_LENGTH} characters.")
    return body


def _ensure_posted_externally(
    provider: str,
    external_review_id: str | None,
    body: str,
    provider_client: ReviewProvider | None,
) -> None:
    """The provider-routing decision, extracted as a pure function so it
    is directly unit-testable with no database: a `'manual'` review needs
    no external post at all; anything else needs a configured
    `ReviewProvider` (`provider_client`, or `resolve_provider()` as a
    fallback) -- raises `ReputationProviderNotConfiguredError` rather than
    silently skipping the post. No non-`'manual'` `Review` row can exist
    yet (`ck_reputation_reviews_provider`, `product/reputation/models.py`),
    so this branch is unreachable through the full stack until a real
    Phase 12.2 provider is built -- it is proven correct by direct unit
    test today (`tests/reputation/test_responses_unit.py`) rather than by
    an integration test that would first need a database row this phase
    cannot legally create."""
    if provider == PROVIDER_MANUAL:
        return
    client = provider_client if provider_client is not None else resolve_provider(provider)
    if client is None:
        raise ReputationProviderNotConfiguredError(provider)
    assert external_review_id is not None  # non-manual reviews always carry one
    client.post_response(external_review_id=external_review_id, body=body)


def create_response(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    *,
    body: str,
    provider_client: ReviewProvider | None = None,
) -> ReviewResponseView:
    require(actor_user_id, tenant_id, resource=REVIEW_RESOURCE, action="respond")
    validated_body = _validate_body(body)

    with tenant_session_scope(tenant_id) as session:
        review_row = session.get(Review, review_id)
        if review_row is None or review_row.tenant_id != tenant_id:
            raise ReputationReferenceNotFoundError("review", review_id)
        provider = review_row.provider
        external_review_id = review_row.external_review_id

    _ensure_posted_externally(provider, external_review_id, validated_body, provider_client)

    response_id = uuid.uuid4()
    with tenant_session_scope(tenant_id) as session:
        review_row = session.get(Review, review_id)
        assert review_row is not None
        session.add(
            ReviewResponse(
                id=response_id,
                tenant_id=tenant_id,
                review_id=review_id,
                body=validated_body,
                posted_by_user_id=actor_user_id,
            )
        )
        review_row.status = REVIEW_STATUS_RESPONDED
        session.flush()

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="reputation.review.responded",
        resource_type="reputation.review",
        resource_id=str(review_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"response_id": str(response_id)},
    )
    publish(
        Event(
            type=REVIEW_RESPONDED_EVENT_TYPE,
            version=REVIEW_RESPONDED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"review_id": str(review_id), "response_id": str(response_id)},
        )
    )

    with tenant_session_scope(tenant_id) as session:
        row = session.get(ReviewResponse, response_id)
        assert row is not None
        session.expunge(row)
    return _to_view(row)


def list_responses(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ReviewResponseView]:
    require(actor_user_id, tenant_id, resource=REVIEW_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        review_row = session.get(Review, review_id)
        if review_row is None or review_row.tenant_id != tenant_id:
            raise ReputationReferenceNotFoundError("review", review_id)
        rows = (
            session.execute(
                select(ReviewResponse)
                .where(
                    ReviewResponse.tenant_id == tenant_id,
                    ReviewResponse.review_id == review_id,
                )
                .order_by(ReviewResponse.created_at.asc())
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
    "REVIEW_RESPONDED_EVENT_TYPE",
    "ReviewResponseView",
    "create_response",
    "list_responses",
]
