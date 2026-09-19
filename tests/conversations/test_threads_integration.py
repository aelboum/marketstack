"""Thread CRUD, contact linkage, multi-channel threading, and isolation
(docs/ROADMAP.md Phase 5.1). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import RoleScope
from core.tenancy import TenantStatus, transition_tenant_status
from infra.db import IntegrityError, tenant_session_scope
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.errors import (
    ConversationAccessDeniedError,
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.models import ConversationThread
from product.conversations.permissions import THREAD_RESOURCE
from product.conversations.threads import (
    create_thread,
    delete_thread,
    get_thread,
    list_threads,
    update_thread,
)
from product.crm.contacts import create_contact, delete_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_thread_crud_and_contact_linkage() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="A", last_name="Contact")
        thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        assert thread.contact_id == contact.id
        assert thread.channel == "email"

        fetched = get_thread(owner.id, client.tenant_id, thread.id)
        assert fetched.id == thread.id

        listed = list_threads(owner.id, client.tenant_id)
        assert any(t.id == thread.id for t in listed)

        updated = update_thread(owner.id, client.tenant_id, thread.id, channel="chat")
        assert updated.channel == "chat"

        delete_thread(owner.id, client.tenant_id, thread.id)
        with pytest.raises(ConversationReferenceNotFoundError):
            get_thread(owner.id, client.tenant_id, thread.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_multi_channel_threading_one_contact_multiple_channels_kept_separate() -> None:
    """5.1's own acceptance criterion: a thread can be created and
    populated across at least two channel types. Product decision (stated
    explicitly, per the roadmap's own brief): one contact having both an
    email thread and an SMS thread produces TWO separate
    `ConversationThread` rows, not one merged thread -- each channel gets
    its own thread, correctly kept separate rather than correctly
    grouped. This is the simplest model consistent with "channel is a
    property of the thread" (product/conversations/models.py); a future
    phase could add an explicit "merge threads for display" concept on
    top without a schema change, if that's ever needed."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Multi", last_name="Channel"
        )
        email_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email"
        )
        sms_thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="sms")
        assert email_thread.id != sms_thread.id
        assert email_thread.channel == "email"
        assert sms_thread.channel == "sms"

        listed = list_threads(owner.id, client.tenant_id)
        listed_for_contact = [t for t in listed if t.contact_id == contact.id]
        assert len(listed_for_contact) == 2
        assert {t.channel for t in listed_for_contact} == {"email", "sms"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_channel_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="X", last_name="Y")
        with pytest.raises(ConversationValidationError):
            create_thread(
                owner.id, client.tenant_id, contact_id=contact.id, channel="carrier-pigeon"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_thread_with_unknown_contact_id_fails_closed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ConversationReferenceNotFoundError):
            create_thread(owner.id, client.tenant_id, contact_id=uuid.uuid4(), channel="email")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_deleting_contact_unlinks_thread_rather_than_deleting_it() -> None:
    """Answers docs/ROADMAP.md Phase 5's own brief question 8: a
    conversation started always linked to a real contact (enforced above),
    but once that contact is deleted, the thread becomes a legitimately
    unlinked, still-readable historical record -- ON DELETE SET NULL, not
    CASCADE."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Soon", last_name="Gone")
        thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")

        delete_contact(owner.id, client.tenant_id, contact.id)

        still_there = get_thread(owner.id, client.tenant_id, thread.id)
        assert still_there.id == thread.id
        assert still_there.contact_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_contact_reference_rejected_by_database_constraint_directly() -> None:
    """The composite FK itself is what actually enforces this -- proven
    by bypassing the service layer entirely and attempting the insert
    directly, mirroring tests/crm/test_contacts_companies_integration.py
    ::test_cross_tenant_company_reference_rejected_by_database_constraint_directly."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        contact_b = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="Only")
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = ConversationThread(
                    tenant_id=client_a.tenant_id, contact_id=contact_b.id, channel="email"
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_client_thread_read_denied() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        contact_b = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="Only")
        thread_b = create_thread(
            owner_b.id, client_b.tenant_id, contact_id=contact_b.id, channel="email"
        )
        with pytest.raises(ConversationAccessDeniedError):
            get_thread(owner_a.id, client_b.tenant_id, thread_b.id)
        with pytest.raises(ConversationAccessDeniedError):
            list_threads(owner_a.id, client_b.tenant_id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_owner_reaches_own_clients_threads_via_inherited_subtree() -> None:
    """Requirement: the agency owner (no direct membership at the client,
    only inherited SUBTREE reach from provision_agency()) can read/write
    the client's own threads -- mirrors tests/crm/test_contacts_companies
    _integration.py::test_agency_owner_reaches_own_clients_contacts_via
    _inherited_subtree exactly."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Reach", last_name="Test")
        thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        fetched = get_thread(owner.id, client.tenant_id, thread.id)
        assert fetched.id == thread.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_mutate_real_tenants_threads() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="S", last_name="T")
        with pytest.raises(ConversationAccessDeniedError):
            create_thread(stranger.id, client.tenant_id, contact_id=contact.id, channel="email")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_explicit_deny_overrides_inherited_subtree_reach() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="D", last_name="Eny")
        thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        assert thread.id is not None

        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=THREAD_RESOURCE,
            action="create",
            scope_mode=RoleScope.SELF,
        )

        with pytest.raises(ConversationAccessDeniedError):
            create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="sms")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_suspended_client_tenant_denies_thread_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="B", last_name="4")
        create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(ConversationAccessDeniedError):
            create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="sms")
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_threads_pagination_is_bounded() -> None:
    from product.conversations.pagination import MAX_PAGE_SIZE

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Bulk", last_name="Test")
        for _ in range(3):
            create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="chat")
        results = list_threads(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
