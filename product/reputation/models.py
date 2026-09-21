"""ORM models for the `reputation` schema (docs/ROADMAP.md Phase 12.1-12.3).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like every other `product/*/models.py` -- this module
never imports `sqlalchemy` directly.

**All three tables are ordinary RLS-scoped, tenant-owned data** -- unlike
`product/websites/models.py::Website` or `product/telephony/models.py
::PhoneNumber`, nothing here needs an untenanted public lookup key: every
read/write happens with an already-established `tenant_id` (an
authenticated actor, or a review recorded/synced by an operator), so there
is no reason to deviate from the default RLS-scoped shape.

**`ReviewRequest.contact_id`** composite-FKs against `crm.contacts`' own
`UniqueConstraint(tenant_id, id)` (mirrors `product/appointments/models.py
::Appointment`'s identical `crm.contacts` composite-FK shape,
`docs/ADR/0010-reputation-depends-on-crm.md`) -- structurally impossible
for a request to reference another tenant's contact. `ON DELETE CASCADE`:
a review request has no meaning without the contact it was sent to,
mirroring `product/websites/models.py::Page.website_id`'s identical
"child has no meaning without its parent" reasoning, not
`Appointment.contact_id`'s `SET NULL` (an appointment's own booking
remains meaningful without a contact; a review *request* does not).

**`Review.review_request_id`** is nullable and composite-FKs against
`reputation.review_requests`' own `UniqueConstraint(tenant_id, id)`, `ON
DELETE SET NULL` -- a review is a standalone fact (a customer's actual
review, however it was recorded) that must survive the deletion of the
request that may have prompted it; only the *link* is severed, mirroring
`crm.contacts.company_id`'s own `SET NULL` reasoning
(`product/crm/models.py` module docstring: "deleting a
contact/company must not destroy an in-progress deal, only unlink it").

**`ReviewResponse.review_id`** composite-FKs against `reputation.reviews`'
own `UniqueConstraint(tenant_id, id)`, `ON DELETE CASCADE` -- a response
has no meaning without the review it responds to, the same `Page.website_id`
shape.

**Closed-vocabulary status/provider columns carry a real `CheckConstraint`,
not just service-layer validation** -- mirrors
`product/appointments/models.py::AvailabilityRule`'s own
`day_of_week`/`start_time`/`end_time` bounds-checking precedent: a defense
against a row ever reaching an invalid state via any write path, not only
the ones `product/reputation/*.py`'s own service layer happens to cover
today.

**`Review.rating`** is bounded `1..5` by `CheckConstraint`, the same
"defense in depth beyond service-layer validation" reasoning.

**`Review.body`/`ReviewResponse.body`** are bounded `String`, never
`Text`/unbounded -- imported or customer-submitted review content must
never grow into an unbounded blob (`docs/ROADMAP.md` Phase 12's own
"bound imported data" requirement).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    Base,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

MAX_AUTHOR_NAME_LENGTH = 255
MAX_REVIEW_BODY_LENGTH = 4000
MAX_RESPONSE_BODY_LENGTH = 4000
MAX_FAILURE_REASON_LENGTH = 500
MAX_EXTERNAL_REVIEW_ID_LENGTH = 255

REQUEST_STATUS_PENDING = "pending"
REQUEST_STATUS_SENT = "sent"
REQUEST_STATUS_FAILED = "failed"
REQUEST_STATUS_CANCELLED = "cancelled"
REQUEST_STATUS_FULFILLED = "fulfilled"
REQUEST_STATUSES = (
    REQUEST_STATUS_PENDING,
    REQUEST_STATUS_SENT,
    REQUEST_STATUS_FAILED,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_FULFILLED,
)

REQUEST_CHANNEL_EMAIL = "email"
REQUEST_CHANNELS = (REQUEST_CHANNEL_EMAIL,)

PROVIDER_MANUAL = "manual"
REVIEW_PROVIDERS = (PROVIDER_MANUAL,)

REVIEW_STATUS_NEW = "new"
REVIEW_STATUS_RESPONDED = "responded"
REVIEW_STATUSES = (REVIEW_STATUS_NEW, REVIEW_STATUS_RESPONDED)


class ReviewRequest(Base):
    """One outbound request asking a contact to leave a review
    (docs/ROADMAP.md Phase 12.1). Ordinary RLS-scoped, tenant-owned data."""

    __tablename__ = "review_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_reputation_review_requests_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_reputation_review_requests_tenant_contact",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'cancelled', 'fulfilled')",
            name="ck_reputation_review_requests_status",
        ),
        CheckConstraint(
            "channel IN ('email')",
            name="ck_reputation_review_requests_channel",
        ),
        Index("ix_reputation_review_requests_tenant_id", "tenant_id"),
        Index("ix_reputation_review_requests_contact_id", "contact_id"),
        {"schema": "reputation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=REQUEST_CHANNEL_EMAIL
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=REQUEST_STATUS_PENDING
    )
    failure_reason: Mapped[str | None] = mapped_column(String(MAX_FAILURE_REASON_LENGTH))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Review(Base):
    """A customer review, however it was recorded -- manually today
    (docs/ROADMAP.md Phase 12.1's own scope), via a real provider adapter
    once one is built (Phase 12.2, deliberately deferred -- see
    `product/reputation/providers.py`'s own module docstring). Ordinary
    RLS-scoped, tenant-owned data."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_reputation_reviews_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "review_request_id"],
            ["reputation.review_requests.tenant_id", "reputation.review_requests.id"],
            name="fk_reputation_reviews_tenant_review_request",
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider",
            "external_review_id",
            name="uq_reputation_reviews_tenant_provider_external_id",
        ),
        CheckConstraint("provider IN ('manual')", name="ck_reputation_reviews_provider"),
        CheckConstraint("status IN ('new', 'responded')", name="ck_reputation_reviews_status"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reputation_reviews_rating"),
        Index("ix_reputation_reviews_tenant_id", "tenant_id"),
        Index("ix_reputation_reviews_review_request_id", "review_request_id"),
        {"schema": "reputation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    review_request_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=PROVIDER_MANUAL
    )
    # NULL for a manually-recorded review (no external identifier exists);
    # populated once a real provider adapter imports a review by its own
    # id. NULLs are not considered equal by Postgres' own UNIQUE constraint
    # semantics, so multiple manual reviews never collide on this column.
    external_review_id: Mapped[str | None] = mapped_column(String(MAX_EXTERNAL_REVIEW_ID_LENGTH))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    author_name: Mapped[str] = mapped_column(String(MAX_AUTHOR_NAME_LENGTH), nullable=False)
    body: Mapped[str | None] = mapped_column(String(MAX_REVIEW_BODY_LENGTH))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=REVIEW_STATUS_NEW
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class ReviewResponse(Base):
    """A response posted to a review (docs/ROADMAP.md Phase 12.3).
    Ordinary RLS-scoped, tenant-owned data."""

    __tablename__ = "review_responses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_reputation_review_responses_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "review_id"],
            ["reputation.reviews.tenant_id", "reputation.reviews.id"],
            name="fk_reputation_review_responses_tenant_review",
            ondelete="CASCADE",
        ),
        Index("ix_reputation_review_responses_tenant_id", "tenant_id"),
        Index("ix_reputation_review_responses_review_id", "review_id"),
        {"schema": "reputation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(String(MAX_RESPONSE_BODY_LENGTH), nullable=False)
    posted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


__all__ = [
    "MAX_AUTHOR_NAME_LENGTH",
    "MAX_EXTERNAL_REVIEW_ID_LENGTH",
    "MAX_FAILURE_REASON_LENGTH",
    "MAX_RESPONSE_BODY_LENGTH",
    "MAX_REVIEW_BODY_LENGTH",
    "PROVIDER_MANUAL",
    "REQUEST_CHANNELS",
    "REQUEST_CHANNEL_EMAIL",
    "REQUEST_STATUSES",
    "REQUEST_STATUS_CANCELLED",
    "REQUEST_STATUS_FAILED",
    "REQUEST_STATUS_FULFILLED",
    "REQUEST_STATUS_PENDING",
    "REQUEST_STATUS_SENT",
    "REVIEW_PROVIDERS",
    "REVIEW_STATUSES",
    "REVIEW_STATUS_NEW",
    "REVIEW_STATUS_RESPONDED",
    "Review",
    "ReviewRequest",
    "ReviewResponse",
]
