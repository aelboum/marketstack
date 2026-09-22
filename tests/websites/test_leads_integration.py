"""`product/websites/leads.py::capture_lead()`/`list_lead_submissions()`
(docs/ROADMAP.md Phase 22, scope item (a)) -- contact matching/creation,
idempotency, non-enumerating page resolution, audit, and the
`websites.lead_captured` event. Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.idempotency import IdempotencyKeyReusedError
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import get_contact
from product.foundation.events import subscribe
from product.websites.errors import WebsiteReferenceNotFoundError, WebsiteValidationError
from product.websites.leads import (
    LEAD_CAPTURED_EVENT_TYPE,
    capture_lead,
    list_lead_submissions,
)
from product.websites.pages import create_page, publish_page
from product.websites.websites import create_website

from tests.websites._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _published_page(owner_id, tenant_id):
    website = create_website(owner_id, tenant_id, slug=_name("site"), name="Site")
    page = create_page(owner_id, tenant_id, website.id, slug=_name("home"), title="Home")
    publish_page(owner_id, tenant_id, page.id)
    return website, page


def test_capture_lead_creates_contact_and_submission() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        result = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            phone=None,
            message="Interested in your services",
            idempotency_key="key-1",
        )
        assert result.is_replay is False

        submissions = list_lead_submissions(owner.id, client.tenant_id, website.id)
        assert len(submissions) == 1
        assert submissions[0].id == result.submission_id
        assert submissions[0].email == "jane@example.com"
        assert submissions[0].contact_id is not None

        contact = get_contact(owner.id, client.tenant_id, submissions[0].contact_id)
        assert contact.first_name == "Jane"
        assert contact.email == "jane@example.com"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_matches_existing_contact_by_email_no_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        first = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="repeat@example.com",
            phone=None,
            message=None,
            idempotency_key="key-a",
        )
        second = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="repeat@example.com",
            phone="+15551234567",
            message="Second visit",
            idempotency_key="key-b",
        )
        first_submission = list_lead_submissions(owner.id, client.tenant_id, website.id)
        contact_ids = {s.contact_id for s in first_submission}
        assert len(contact_ids) == 1
        assert first.submission_id != second.submission_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_idempotent_retry_does_not_create_a_second_submission() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        first = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="idempotent@example.com",
            phone=None,
            message=None,
            idempotency_key="same-key",
        )
        replay = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="idempotent@example.com",
            phone=None,
            message=None,
            idempotency_key="same-key",
        )
        assert replay.is_replay is True
        assert replay.submission_id == first.submission_id

        submissions = list_lead_submissions(owner.id, client.tenant_id, website.id)
        assert len(submissions) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reused_idempotency_key_with_different_payload_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="first@example.com",
            phone=None,
            message=None,
            idempotency_key="shared-key",
        )
        with pytest.raises(IdempotencyKeyReusedError):
            capture_lead(
                client.tenant_id,
                website.id,
                page.id,
                first_name="Other",
                last_name="Person",
                email="different@example.com",
                phone=None,
                message=None,
                idempotency_key="shared-key",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_publishes_event_only_on_real_success() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []
    subscribe(LEAD_CAPTURED_EVENT_TYPE, received.append)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        result = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="event@example.com",
            phone=None,
            message=None,
            idempotency_key="event-key",
        )
        matching = [e for e in received if e.tenant_id == str(client.tenant_id)]
        assert len(matching) == 1
        assert set(matching[0].payload) == {"contact_id", "website_id", "page_id", "submission_id"}
        assert matching[0].payload["submission_id"] == str(result.submission_id)

        # A replay of the same key must not publish a second event.
        capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="event@example.com",
            phone=None,
            message=None,
            idempotency_key="event-key",
        )
        matching_after_replay = [e for e in received if e.tenant_id == str(client.tenant_id)]
        assert len(matching_after_replay) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_records_bounded_audit_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        result = capture_lead(
            client.tenant_id,
            website.id,
            page.id,
            first_name="Jane",
            last_name="Doe",
            email="audit@example.com",
            phone=None,
            message="secret operational detail",
            idempotency_key="audit-key",
        )
        entries = list_audit_log(
            client.tenant_id,
            resource_type="websites.lead_submission",
            resource_id=str(result.submission_id),
        )
        matching = [e for e in entries if e.action == "websites.lead.submitted"]
        assert len(matching) == 1
        metadata = matching[0].entry_metadata
        assert set(metadata) == {"website_id", "page_id", "contact_id"}
        # Never the raw name/email/phone/message.
        assert "secret operational detail" not in str(metadata)
        assert "audit@example.com" not in str(metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_rejects_unknown_page_non_enumerating() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, _page = _published_page(owner.id, client.tenant_id)
        with pytest.raises(WebsiteReferenceNotFoundError):
            capture_lead(
                client.tenant_id,
                website.id,
                uuid.uuid4(),
                first_name="Jane",
                last_name="Doe",
                email="x@example.com",
                phone=None,
                message=None,
                idempotency_key="unknown-page",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_rejects_unpublished_page_identically_to_unknown() -> None:
    """An unpublished (draft) page must be indistinguishable from an
    unknown one -- the same exception, never a hint that the page exists
    but isn't live yet."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website = create_website(owner.id, client.tenant_id, slug=_name("site"), name="Site")
        draft_page = create_page(
            owner.id, client.tenant_id, website.id, slug=_name("draft"), title="Draft"
        )
        with pytest.raises(WebsiteReferenceNotFoundError):
            capture_lead(
                client.tenant_id,
                website.id,
                draft_page.id,
                first_name="Jane",
                last_name="Doe",
                email="draft@example.com",
                phone=None,
                message=None,
                idempotency_key="draft-page",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_cross_tenant_page_is_rejected() -> None:
    """A page real in tenant B must not be reachable via tenant A's
    website_id/tenant_id."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        website_a, _page_a = _published_page(owner_a.id, client_a.tenant_id)
        _website_b, page_b = _published_page(owner_b.id, client_b.tenant_id)
        with pytest.raises(WebsiteReferenceNotFoundError):
            capture_lead(
                client_a.tenant_id,
                website_a.id,
                page_b.id,
                first_name="Jane",
                last_name="Doe",
                email="cross@example.com",
                phone=None,
                message=None,
                idempotency_key="cross-tenant",
            )
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_capture_lead_validates_required_fields() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        website, page = _published_page(owner.id, client.tenant_id)
        with pytest.raises(WebsiteValidationError):
            capture_lead(
                client.tenant_id,
                website.id,
                page.id,
                first_name="",
                last_name="Doe",
                email="x@example.com",
                phone=None,
                message=None,
                idempotency_key="bad-input",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_lead_submissions_is_tenant_isolated() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        website_a, page_a = _published_page(owner_a.id, client_a.tenant_id)
        website_b, page_b = _published_page(owner_b.id, client_b.tenant_id)
        capture_lead(
            client_a.tenant_id,
            website_a.id,
            page_a.id,
            first_name="A",
            last_name="Lead",
            email="a@example.com",
            phone=None,
            message=None,
            idempotency_key="a-key",
        )
        capture_lead(
            client_b.tenant_id,
            website_b.id,
            page_b.id,
            first_name="B",
            last_name="Lead",
            email="b@example.com",
            phone=None,
            message=None,
            idempotency_key="b-key",
        )
        a_submissions = list_lead_submissions(owner_a.id, client_a.tenant_id, website_a.id)
        assert [s.email for s in a_submissions] == ["a@example.com"]
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
