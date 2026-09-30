"""`create_or_reuse_contact_from_trusted_source_by_phone()` (docs/ROADMAP.md
Phase 30 "Unified Inbox", `docs/ADR/0019-conversations-depends-on-crm.md`,
`docs/ADR/0018-inbound-phone-caller-contact-trust-boundary.md` point 8).
Real disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import (
    ContactView,
    create_or_reuse_contact_from_trusted_source_by_phone,
    get_contact,
    update_contact,
)
from product.crm.errors import CrmReferenceNotFoundError

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_unknown_phone_creates_exactly_one_tenant_scoped_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+15551230001", source="sms:unverified"
        )
        assert contact.tenant_id == client.tenant_id
        assert contact.phone == "+15551230001"

        fetched = get_contact(owner.id, client.tenant_id, contact.id)
        assert fetched.id == contact.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_repeated_inbound_delivery_reuses_existing_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        first = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+15551230002", source="sms:unverified"
        )
        second = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+15551230002", source="sms:unverified"
        )
        assert first.id == second.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_phone_normalization_is_applied_consistently() -> None:
    """Formatting-only variants of the same number (spaces/hyphens/
    parentheses, per `product.foundation.values.normalize_phone_number()`)
    resolve to the same contact."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        first = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+1 (555) 123-0003", source="whatsapp:unverified"
        )
        second = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+15551230003", source="whatsapp:unverified"
        )
        assert first.id == second.id
        assert first.phone == "+15551230003"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_same_phone_in_different_tenants_creates_independent_contacts() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        contact_a = create_or_reuse_contact_from_trusted_source_by_phone(
            client_a.tenant_id, phone="+15551230004", source="sms:unverified"
        )
        contact_b = create_or_reuse_contact_from_trusted_source_by_phone(
            client_b.tenant_id, phone="+15551230004", source="sms:unverified"
        )
        assert contact_a.id != contact_b.id
        assert contact_a.tenant_id != contact_b.tenant_id

        # Tenant A's resolution must never be reachable/visible from tenant B.
        with pytest.raises(CrmReferenceNotFoundError):
            get_contact(owner.id, client_b.tenant_id, contact_a.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_correlation_match_never_overwrites_trusted_contact_fields() -> None:
    """ADR-0018 point 8 / ADR-0019 Decision 3: a phone match must never
    mutate an existing contact's trusted fields, unlike the email-keyed
    `create_or_update_contact_from_trusted_source()`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id, phone="+15551230005", source="sms:unverified"
        )
        update_contact(owner.id, client.tenant_id, created.id, first_name="Real", last_name="Name")

        reused = create_or_reuse_contact_from_trusted_source_by_phone(
            client.tenant_id,
            phone="+15551230005",
            source="sms:unverified",
            first_name="Someone",
            last_name="Else",
        )
        assert reused.id == created.id
        assert reused.first_name == "Real"
        assert reused.last_name == "Name"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_duplicate_delivery_creates_exactly_one_contact() -> None:
    """Two real threads race to resolve the SAME inbound phone number for
    the SAME tenant, synchronized with a `threading.Barrier` so they
    genuinely contend -- mirrors
    tests/conversations/test_concurrency_integration.py's own shape.
    `acquire_tenant_advisory_lock()` (not a unique constraint, since
    `crm.contacts` has none on phone) is what actually prevents the
    duplicate; this test proves that claim against a real database."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, ContactView] = {}

        def _attempt(label: str) -> None:
            barrier.wait()
            results[label] = create_or_reuse_contact_from_trusted_source_by_phone(
                client.tenant_id, phone="+15551230006", source="sms:unverified"
            )

        thread_a = threading.Thread(target=_attempt, args=("a",))
        thread_b = threading.Thread(target=_attempt, args=("b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)

        assert results["a"].id == results["b"].id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
