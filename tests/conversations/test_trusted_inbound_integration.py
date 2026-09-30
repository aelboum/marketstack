"""`create_thread_from_trusted_inbound()` (docs/ROADMAP.md Phase 30
"Unified Inbox", `docs/ADR/0019-conversations-depends-on-crm.md`,
`docs/ADR/0018-inbound-phone-caller-contact-trust-boundary.md`). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.errors import ConversationValidationError
from product.conversations.threads import (
    ThreadView,
    create_thread,
    create_thread_from_trusted_inbound,
    get_thread,
)
from product.crm.contacts import create_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_first_trusted_inbound_delivery_creates_contact_and_thread() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        thread = create_thread_from_trusted_inbound(
            client.tenant_id, channel="sms", from_phone="+15559990001", source="sms:unverified"
        )
        assert thread.tenant_id == client.tenant_id
        assert thread.contact_id is not None
        assert thread.channel == "sms"

        fetched = get_thread(owner.id, client.tenant_id, thread.id)
        assert fetched.id == thread.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_repeated_delivery_reuses_the_same_thread() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        first = create_thread_from_trusted_inbound(
            client.tenant_id, channel="sms", from_phone="+15559990002", source="sms:unverified"
        )
        second = create_thread_from_trusted_inbound(
            client.tenant_id, channel="sms", from_phone="+15559990002", source="sms:unverified"
        )
        assert first.id == second.id
        assert first.contact_id == second.contact_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_sms_path_works() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        thread = create_thread_from_trusted_inbound(
            client.tenant_id, channel="sms", from_phone="+15559990003", source="sms:unverified"
        )
        assert thread.channel == "sms"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_whatsapp_path_works() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        thread = create_thread_from_trusted_inbound(
            client.tenant_id,
            channel="whatsapp",
            from_phone="+15559990004",
            source="whatsapp:unverified",
        )
        assert thread.channel == "whatsapp"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_call_path_works() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        thread = create_thread_from_trusted_inbound(
            client.tenant_id,
            channel="call",
            from_phone="+15559990005",
            source="voice_call:unverified",
        )
        assert thread.channel == "call"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_different_channels_for_the_same_phone_get_separate_threads() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        sms_thread = create_thread_from_trusted_inbound(
            client.tenant_id, channel="sms", from_phone="+15559990006", source="sms:unverified"
        )
        whatsapp_thread = create_thread_from_trusted_inbound(
            client.tenant_id,
            channel="whatsapp",
            from_phone="+15559990006",
            source="whatsapp:unverified",
        )
        assert sms_thread.contact_id == whatsapp_thread.contact_id
        assert sms_thread.id != whatsapp_thread.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_email_channel_is_rejected_for_trusted_inbound() -> None:
    """Only the phone-bearing channels (sms/whatsapp/call) are accepted --
    email has no phone identifier to correlate on."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ConversationValidationError):
            create_thread_from_trusted_inbound(
                client.tenant_id,
                channel="email",
                from_phone="+15559990007",
                source="sms:unverified",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tenant_a_cannot_resolve_tenant_bs_contact_via_the_same_phone() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        thread_a = create_thread_from_trusted_inbound(
            client_a.tenant_id, channel="sms", from_phone="+15559990008", source="sms:unverified"
        )
        thread_b = create_thread_from_trusted_inbound(
            client_b.tenant_id, channel="sms", from_phone="+15559990008", source="sms:unverified"
        )
        assert thread_a.tenant_id != thread_b.tenant_id
        assert thread_a.contact_id != thread_b.contact_id
        assert thread_a.id != thread_b.id
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_trusted_inbound_path_does_not_establish_authentication_or_ownership() -> None:
    """A trusted-inbound-created thread/contact grants no authorization --
    reading it still goes through the ordinary authenticated
    `get_thread()`/RBAC path exactly like any other thread; there is no
    bypass and no special "caller-owns-this" claim recorded anywhere."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        thread = create_thread_from_trusted_inbound(
            client.tenant_id,
            channel="call",
            from_phone="+15559990009",
            source="voice_call:unverified",
        )
        # Ordinary authenticated read still requires an ordinary actor with
        # ordinary RBAC -- this call succeeding is the point: no special
        # "caller-owns-this" identity was minted by the trusted path.
        fetched = get_thread(owner.id, client.tenant_id, thread.id)
        assert fetched.assigned_to_user_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_existing_authenticated_create_thread_is_unchanged() -> None:
    """`create_thread()`'s own authenticated, actor-scoped contract is
    unaffected by adding the trusted inbound path alongside it."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Direct", last_name="Caller"
        )
        thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="chat")
        assert thread.contact_id == contact.id
        assert thread.channel == "chat"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_duplicate_delivery_creates_exactly_one_thread() -> None:
    """Two real threads race to deliver the SAME inbound phone identifier
    on the SAME channel for the SAME tenant -- mirrors
    tests/conversations/test_concurrency_integration.py's own shape.
    `acquire_tenant_advisory_lock()` (not a unique constraint, since
    `conversations.threads` has none on `(tenant_id, contact_id, channel)`)
    is what actually prevents the duplicate."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, ThreadView] = {}

        def _attempt(label: str) -> None:
            barrier.wait()
            results[label] = create_thread_from_trusted_inbound(
                client.tenant_id,
                channel="sms",
                from_phone="+15559990010",
                source="sms:unverified",
            )

        thread_a = threading.Thread(target=_attempt, args=("a",))
        thread_b = threading.Thread(target=_attempt, args=("b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)

        assert results["a"].id == results["b"].id
        assert results["a"].contact_id == results["b"].contact_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
