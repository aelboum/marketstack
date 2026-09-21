"""`product/reputation/purge.py`: the consolidated tenant-purge
participant covering `reputation.review_requests`/`reputation.reviews`/
`reputation.review_responses`, its dependency ordering, and its
tenant-scoping -- purging tenant A must never touch tenant B's rows
(docs/ROADMAP.md Phase 12). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.email.provider import FakeEmailProvider
from infra.db import select, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import create_contact
from product.reputation.models import Review, ReviewRequest, ReviewResponse
from product.reputation.purge import ReputationDataPurgeParticipant
from product.reputation.responses import create_response
from product.reputation.review_requests import create_review_request
from product.reputation.reviews import record_review

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


def _seed(owner_id, tenant_id):
    contact = create_contact(
        owner_id, tenant_id, first_name="R", last_name="C", email=f"{_name('r')}@example.test"
    )
    request = create_review_request(
        owner_id, tenant_id, contact.id, email_provider=FakeEmailProvider()
    )
    review = record_review(
        owner_id, tenant_id, rating=5, author_name="R C", review_request_id=request.id
    )
    response = create_response(owner_id, tenant_id, review.id, body="Thanks!")
    return request, review, response


def test_purge_deletes_only_the_target_tenants_reputation_data() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        request_a, review_a, response_a = _seed(owner_a.id, client_a.tenant_id)
        request_b, review_b, response_b = _seed(owner_b.id, client_b.tenant_id)

        ReputationDataPurgeParticipant().purge_tenant_data(client_a.tenant_id)

        with tenant_session_scope(client_a.tenant_id) as session:
            assert session.get(ReviewRequest, request_a.id) is None
            assert session.get(Review, review_a.id) is None
            assert session.get(ReviewResponse, response_a.id) is None

        with tenant_session_scope(client_b.tenant_id) as session:
            assert session.get(ReviewRequest, request_b.id) is not None
            assert session.get(Review, review_b.id) is not None
            assert session.get(ReviewResponse, response_b.id) is not None
    finally:
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_purge_participant_is_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed(owner.id, client.tenant_id)

        participant = ReputationDataPurgeParticipant()
        participant.purge_tenant_data(client.tenant_id)
        # A second run against an already-empty tenant must not raise.
        participant.purge_tenant_data(client.tenant_id)

        with tenant_session_scope(client.tenant_id) as session:
            leftover = (
                session.execute(
                    select(ReviewRequest).where(ReviewRequest.tenant_id == client.tenant_id)
                )
                .scalars()
                .all()
            )
            assert leftover == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
