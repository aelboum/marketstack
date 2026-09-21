"""`product/reputation/responses.py`: responding to a (manual) review,
tenant isolation, and authorization (docs/ROADMAP.md Phase 12.3). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.foundation.events import subscribe
from product.reputation.errors import (
    ReputationAccessDeniedError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.responses import (
    REVIEW_RESPONDED_EVENT_TYPE,
    create_response,
    list_responses,
)
from product.reputation.reviews import get_review, record_review

from tests.reputation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


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


# --- Valid creation --------------------------------------------------------------


def test_create_response_to_manual_review() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        review = record_review(owner.id, client.tenant_id, rating=2, author_name="Unhappy")
        response = create_response(
            owner.id, client.tenant_id, review.id, body="Sorry to hear that, let's fix it."
        )
        assert response.review_id == review.id
        listed = list_responses(owner.id, client.tenant_id, review.id)
        assert [r.id for r in listed] == [response.id]
        updated_review = get_review(owner.id, client.tenant_id, review.id)
        assert updated_review.status == "responded"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_response_publishes_responded_event() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []

    def _handler(event):
        received.append(event)

    subscribe(REVIEW_RESPONDED_EVENT_TYPE, _handler)
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="A")
        response = create_response(owner.id, client.tenant_id, review.id, body="Thanks!")
        matching = [e for e in received if e.payload.get("response_id") == str(response.id)]
        assert len(matching) == 1
        assert matching[0].payload["review_id"] == str(review.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_response_audit_entry_recorded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="A")
        create_response(owner.id, client.tenant_id, review.id, body="Thanks a lot!")
        entries = list_audit_log(
            client.tenant_id, resource_type="reputation.review", resource_id=str(review.id)
        )
        matching = [e for e in entries if e.action == "reputation.review.responded"]
        assert len(matching) == 1
        for entry in matching:
            assert "Thanks a lot!" not in str(entry.entry_metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input ------------------------------------------------------------


def test_create_response_rejects_empty_body() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="A")
        with pytest.raises(ReputationValidationError):
            create_response(owner.id, client.tenant_id, review.id, body="   ")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_response_rejects_unknown_review() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationReferenceNotFoundError):
            create_response(owner.id, client.tenant_id, uuid.uuid4(), body="Thanks!")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation ------------------------------------------------------------


def test_cannot_respond_to_cross_tenant_review() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        other_review = record_review(
            other_owner.id, other_client.tenant_id, rating=5, author_name="Other"
        )
        with pytest.raises(ReputationReferenceNotFoundError):
            create_response(owner.id, client.tenant_id, other_review.id, body="Nope")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


# --- Authorization ---------------------------------------------------------------


def test_unrelated_actor_cannot_respond() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="A")
        with pytest.raises(ReputationAccessDeniedError):
            create_response(unrelated.id, client.tenant_id, review.id, body="Nope")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_respond_to_a_review() -> None:
    """`product/reputation/event_handlers.py`'s own grant: `respond` is
    granted to `member`, not owner-only (an ordinary day-to-day action)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        review = record_review(owner.id, client.tenant_id, rating=5, author_name="A")
        response = create_response(member.id, client.tenant_id, review.id, body="Thanks!")
        assert response.posted_by_user_id == member.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)
