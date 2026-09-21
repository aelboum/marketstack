"""`product/reputation/review_requests.py`: review request lifecycle,
tenant isolation, authorization, and tenant-lifecycle denial
(docs/ROADMAP.md Phase 12.1). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.email.provider import FakeEmailProvider
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.contacts import create_contact
from product.foundation.events import subscribe
from product.reputation.errors import (
    ReputationAccessDeniedError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import REQUEST_STATUS_CANCELLED, REQUEST_STATUS_SENT
from product.reputation.pagination import MAX_PAGE_SIZE
from product.reputation.review_requests import (
    REQUEST_CREATED_EVENT_TYPE,
    REQUEST_FAILED_EVENT_TYPE,
    REQUEST_SENT_EVENT_TYPE,
    cancel_review_request,
    create_review_request,
    get_review_request,
    list_review_requests,
)

from tests.reputation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _email_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """See `tests/conversations/test_email_sending_integration.py`'s own
    identical fixture docstring -- `get_email_config()` is process-wide
    `@lru_cache`'d, so this only matters the first time it is ever called
    in a given test process."""
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


def _contact_with_email(owner_id, tenant_id, email: str = "reviewer@example.test"):
    return create_contact(owner_id, tenant_id, first_name="Rev", last_name="Iewer", email=email)


# --- Valid creation, tracked status --------------------------------------------


def test_create_review_request_sends_and_tracks_sent_status() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        provider = FakeEmailProvider()
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=provider
        )
        assert request.status == REQUEST_STATUS_SENT
        assert request.contact_id == contact.id
        assert request.sent_at is not None
        assert request.failure_reason is None
        assert len(provider.sent) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_review_request_tracks_failed_status_on_send_failure() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        failing_provider = FakeEmailProvider(fail=True)
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=failing_provider
        )
        assert request.status == "failed"
        assert request.failure_reason is not None
        assert request.sent_at is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_review_request_publishes_created_sent_events() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received_types: list[str] = []

    def _handler(event):
        received_types.append(event.type)

    subscribe(REQUEST_CREATED_EVENT_TYPE, _handler)
    subscribe(REQUEST_SENT_EVENT_TYPE, _handler)
    subscribe(REQUEST_FAILED_EVENT_TYPE, _handler)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        assert received_types == [REQUEST_CREATED_EVENT_TYPE, REQUEST_SENT_EVENT_TYPE]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_review_request_audit_entries_carry_no_email_address() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id, email="secret@example.test")
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        entries = list_audit_log(
            client.tenant_id,
            resource_type="reputation.review_request",
            resource_id=str(request.id),
        )
        actions = {e.action for e in entries}
        assert "reputation.review_request.created" in actions
        assert "reputation.review_request.sent" in actions
        for entry in entries:
            assert "secret@example.test" not in str(entry.metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input --------------------------------------------------------------


def test_create_review_request_rejects_unsupported_channel() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        with pytest.raises(ReputationValidationError):
            create_review_request(owner.id, client.tenant_id, contact.id, channel="carrier-pigeon")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_review_request_rejects_contact_with_no_email() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="No", last_name="Email")
        with pytest.raises(ReputationValidationError):
            create_review_request(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_review_request_rejects_unknown_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ReputationReferenceNotFoundError):
            create_review_request(owner.id, client.tenant_id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_review_request_rejects_cross_tenant_contact() -> None:
    """The contact must belong to the SAME tenant the request is created
    in -- a contact from another tenant is indistinguishable from an
    unknown one (non-enumerating), proving `get_contact()`'s own tenant
    check is honored across this module boundary too."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        other_contact = _contact_with_email(other_owner.id, other_client.tenant_id)
        with pytest.raises(ReputationReferenceNotFoundError):
            create_review_request(owner.id, client.tenant_id, other_contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


# --- Lifecycle: cancel ----------------------------------------------------------


def test_cancel_sent_review_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        cancelled = cancel_review_request(owner.id, client.tenant_id, request.id)
        assert cancelled.status == REQUEST_STATUS_CANCELLED
        assert cancelled.cancelled_at is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancel_already_cancelled_review_request_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        cancel_review_request(owner.id, client.tenant_id, request.id)
        with pytest.raises(ReputationValidationError):
            cancel_review_request(owner.id, client.tenant_id, request.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation ------------------------------------------------------------


def test_review_requests_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        request = create_review_request(
            owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        with pytest.raises(ReputationReferenceNotFoundError):
            get_review_request(other_owner.id, other_client.tenant_id, request.id)
        listed = list_review_requests(other_owner.id, other_client.tenant_id)
        assert all(r.id != request.id for r in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


# --- Authorization ---------------------------------------------------------------


def test_unrelated_actor_cannot_create_review_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        with pytest.raises(ReputationAccessDeniedError):
            create_review_request(unrelated.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_create_and_read_but_not_cancel() -> None:
    """`product/reputation/event_handlers.py`'s own owner/member grant
    split: member gets create/read, never cancel."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        request = create_review_request(
            member.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
        )
        fetched = get_review_request(member.id, client.tenant_id, request.id)
        assert fetched.id == request.id
        with pytest.raises(ReputationAccessDeniedError):
            cancel_review_request(member.id, client.tenant_id, request.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Tenant lifecycle ----------------------------------------------------------


def test_suspended_tenant_denies_review_request_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact_with_email(owner.id, client.tenant_id)
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(ReputationAccessDeniedError):
            create_review_request(owner.id, client.tenant_id, contact.id)
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Pagination ------------------------------------------------------------


def test_list_review_requests_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for _ in range(3):
            contact = _contact_with_email(
                owner.id, client.tenant_id, email=f"{_name('reviewer')}@example.test"
            )
            create_review_request(
                owner.id, client.tenant_id, contact.id, email_provider=FakeEmailProvider()
            )
        results = list_review_requests(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
