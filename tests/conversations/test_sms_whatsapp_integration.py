"""SMS/WhatsApp provider-neutral interfaces (docs/ROADMAP.md Phase 5.3,
5.4) -- explicitly PARTIAL, see product/conversations/sms.py's own
module docstring for why. These tests prove only what's real: the
`FakeSmsProvider`/`FakeWhatsAppProvider` round-trip through
`send_sms_message()`/`send_whatsapp_message()`, recording a correctly-
shaped outbound message via the same channel-agnostic `create_message()`
the email path uses -- proving 5.1's own acceptance criterion (a thread
populated across at least two channel types) without claiming a live
SMS/WhatsApp send exists. Real disposable Postgres, no network access.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.messages import list_messages
from product.conversations.sms import FakeSmsProvider, SmsProviderError, send_sms_message
from product.conversations.threads import create_thread
from product.conversations.whatsapp import (
    FakeWhatsAppProvider,
    WhatsAppProviderError,
    send_whatsapp_message,
)
from product.crm.contacts import create_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_client_and_thread(owner_id, channel: str):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    contact = create_contact(
        owner_id, client.tenant_id, first_name="P", last_name="Hone", phone="+15551230000"
    )
    thread = create_thread(owner_id, client.tenant_id, contact_id=contact.id, channel=channel)
    return agency, client, thread


def test_send_sms_message_via_fake_provider_records_outbound_message() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id, "sms")
    provider = FakeSmsProvider()
    try:
        message = send_sms_message(
            owner.id,
            client.tenant_id,
            thread.id,
            to_phone="+15551230000",
            body="Fake SMS body",
            provider=provider,
        )
        assert message.direction == "outbound"
        assert len(provider.sent) == 1
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert any(m.id == message.id for m in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_sms_send_failure_does_not_record_a_message() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id, "sms")
    failing_provider = FakeSmsProvider(fail=True)
    try:
        with pytest.raises(SmsProviderError):
            send_sms_message(
                owner.id,
                client.tenant_id,
                thread.id,
                to_phone="+15551230000",
                body="Will fail",
                provider=failing_provider,
            )
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert listed == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_send_whatsapp_message_via_fake_provider_records_outbound_message() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id, "whatsapp")
    provider = FakeWhatsAppProvider()
    try:
        message = send_whatsapp_message(
            owner.id,
            client.tenant_id,
            thread.id,
            to_phone="+15551230000",
            body="Fake WhatsApp body",
            provider=provider,
        )
        assert message.direction == "outbound"
        assert len(provider.sent) == 1
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert any(m.id == message.id for m in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_whatsapp_send_failure_does_not_record_a_message() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id, "whatsapp")
    failing_provider = FakeWhatsAppProvider(fail=True)
    try:
        with pytest.raises(WhatsAppProviderError):
            send_whatsapp_message(
                owner.id,
                client.tenant_id,
                thread.id,
                to_phone="+15551230000",
                body="Will fail",
                provider=failing_provider,
            )
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert listed == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_thread_populated_across_three_channel_types() -> None:
    """5.1's own acceptance criterion, satisfied across three channels,
    not just two -- email (tests/conversations/test_email_sending
    _integration.py), sms, and whatsapp all funnel through the identical
    channel-agnostic create_message()."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    contact = create_contact(
        owner.id, client.tenant_id, first_name="Tri", last_name="Channel", phone="+15559998888"
    )
    try:
        email_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email"
        )
        sms_thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="sms")
        whatsapp_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="whatsapp"
        )
        send_sms_message(
            owner.id,
            client.tenant_id,
            sms_thread.id,
            to_phone="+15559998888",
            body="sms",
            provider=FakeSmsProvider(),
        )
        send_whatsapp_message(
            owner.id,
            client.tenant_id,
            whatsapp_thread.id,
            to_phone="+15559998888",
            body="whatsapp",
            provider=FakeWhatsAppProvider(),
        )
        assert list_messages(owner.id, client.tenant_id, sms_thread.id)[0].body == "sms"
        assert list_messages(owner.id, client.tenant_id, whatsapp_thread.id)[0].body == "whatsapp"
        assert list_messages(owner.id, client.tenant_id, email_thread.id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
