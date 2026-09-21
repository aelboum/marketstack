"""`product/reputation/reviews.py`: review recording, request-linking
lifecycle, tenant isolation, and authorization (docs/ROADMAP.md Phase
12.1/12.2). Real disposable Postgres. Marked `integration`, excluded from
the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.email.provider import FakeEmailProvider
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.contacts import create_contact
from product.foundation.events import subscribe
from product.reputation.errors import (
    ReputationAccessDeniedError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import REQUEST_STATUS_FULFILLED
from product.reputation.pagination import MAX_PAGE_SIZE
from product.reputation.review_requests import create_review_request, get_review_request
from product.reputation.reviews import (
    REVIEW_RECEIVED_EVENT_TYPE,
    get_review,
    list_reviews,
    record_review,
)

from tests.reputation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _email_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("EMAIL_DEFAULT_SENDER", "no-reply@example.test")


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


# --- Valid creation, manual recording -------------------------------------------


def test_record_review_valid() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        review = record_review(
            owner.id, client.tenant_id, rating=5, author_name="Happy Customer", body="Great!"
        )
        assert review.rating == 5
        assert review.provider == "manual"
        assert review.status == "new"
        fetched = get_review(owner.id, client.tenant_id, review.id)
        assert fetched.id == review.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_publishes_received_event() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []

    def _handler(event):
        received.append(event)

    subscribe(REVIEW_RECEIVED_EVENT_TYPE, _handler)
    try:
        review = record_review(owner.id, client.tenant_id, rating=4, author_name="A")
        matching = [e for e in received if e.payload.get("review_id") == str(review.id)]
        assert len(matching) == 1
        assert matching[0].payload["rating"] == 4
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_audit_never_contains_review_body_or_author() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        review = record_review(
            owner.id,
            client.tenant_id,
            rating=3,
            author_name="Secret Author Name",
            body="Secret review body text",
        )
        entries = list_audit_log(
            client.tenant_id, resource_type="reputation.review", resource_id=str(review.id)
        )
        matching = [e for e in entries if e.action == "reputation.review.recorded"]
        assert len(matching) == 1
        for entry in matching:
            assert "Secret Author Name" not in str(entry.entry_metadata)
            assert "Secret review body text" not in str(entry.entry_metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input ------------------------------------------------------------


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_record_review_rejects_out_of_bounds_rating(rating: int) -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationValidationError):
            record_review(owner.id, client.tenant_id, rating=rating, author_name="A")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_rejects_empty_author_name() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationValidationError):
            record_review(owner.id, client.tenant_id, rating=5, author_name="   ")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_rejects_non_manual_provider() -> None:
    """`docs/ROADMAP.md` Phase 12.2 is deliberately deferred -- only
    `'manual'` is accepted today (`product/reputation/reviews.py
    ::_validate_provider()`)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationValidationError):
            record_review(
                owner.id,
                client.tenant_id,
                rating=5,
                author_name="A",
                provider="google_business_profile",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Linking a review to a review request (fulfillment) -------------------------


def test_record_review_linked_to_sent_request_fulfills_it() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="R", last_name="C", email="r@example.test"
        )
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        review = record_review(
            owner.id,
            client.tenant_id,
            rating=5,
            author_name="R C",
            review_request_id=request.id,
        )
        assert review.review_request_id == request.id
        refreshed_request = get_review_request(owner.id, client.tenant_id, request.id)
        assert refreshed_request.status == REQUEST_STATUS_FULFILLED
        assert refreshed_request.fulfilled_at is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_rejects_linking_to_unknown_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationReferenceNotFoundError):
            record_review(
                owner.id,
                client.tenant_id,
                rating=5,
                author_name="A",
                review_request_id=uuid.uuid4(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_rejects_linking_to_already_fulfilled_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="R", last_name="C", email="r2@example.test"
        )
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        record_review(
            owner.id, client.tenant_id, rating=5, author_name="First", review_request_id=request.id
        )
        with pytest.raises(ReputationValidationError):
            record_review(
                owner.id,
                client.tenant_id,
                rating=4,
                author_name="Second",
                review_request_id=request.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_record_review_rejects_linking_to_cross_tenant_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        contact = create_contact(
            other_owner.id,
            other_client.tenant_id,
            first_name="O",
            last_name="C",
            email="o@example.test",
        )
        other_request = create_review_request(
            other_owner.id, other_client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        with pytest.raises(ReputationReferenceNotFoundError):
            record_review(
                owner.id,
                client.tenant_id,
                rating=5,
                author_name="A",
                review_request_id=other_request.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


# --- Tenant isolation ------------------------------------------------------------


def test_reviews_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="Mine")
        with pytest.raises(ReputationReferenceNotFoundError):
            get_review(other_owner.id, other_client.tenant_id, review.id)
        listed = list_reviews(other_owner.id, other_client.tenant_id)
        assert all(r.id != review.id for r in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


# --- Authorization ---------------------------------------------------------------


def test_unrelated_actor_cannot_record_review() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(ReputationAccessDeniedError):
            record_review(unrelated.id, client.tenant_id, rating=5, author_name="A")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_record_and_read_reviews() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        review = record_review(member.id, client.tenant_id, rating=5, author_name="By Member")
        fetched = get_review(member.id, client.tenant_id, review.id)
        assert fetched.id == review.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Pagination ------------------------------------------------------------


def test_list_reviews_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for _ in range(3):
            record_review(owner.id, client.tenant_id, rating=5, author_name="Bulk")
        results = list_reviews(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
