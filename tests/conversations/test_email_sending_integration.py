"""Outbound email sending (docs/ROADMAP.md Phase 5.2). Real disposable
Postgres, `core.email.provider.FakeEmailProvider` (no real network/SMTP).
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.email.errors import EmailProviderError
from core.email.provider import FakeEmailProvider
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.email_sending import send_email_message
from product.conversations.errors import ConversationValidationError
from product.conversations.messages import list_messages
from product.conversations.threads import create_thread
from product.crm.contacts import create_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _email_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`core.email.get_email_config()` requires `SMTP_HOST` (no default --
    see `core/email/config.py`'s own `EmailConfig.__post_init__()`) even
    when a `provider=` override (here, always `FakeEmailProvider`) means
    the real SMTP host is never actually contacted -- `send_email_message()`
    still calls `get_email_config()` first, for `default_sender`. Set
    once here rather than per-test; `get_email_config()` is
    `@lru_cache`'d process-wide (its own module docstring), so only the
    first successful call's values matter for the rest of this test
    session regardless."""
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("EMAIL_DEFAULT_SENDER", "no-reply@example.test")


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_client_thread_with_contact_email(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    contact = create_contact(
        owner_id, client.tenant_id, first_name="E", last_name="Mail", email="contact@example.test"
    )
    thread = create_thread(owner_id, client.tenant_id, contact_id=contact.id, channel="email")
    return agency, client, thread


def test_send_email_message_succeeds_and_is_recorded() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_thread_with_contact_email(owner.id)
    provider = FakeEmailProvider()
    try:
        message = send_email_message(
            owner.id,
            client.tenant_id,
            thread.id,
            to_email="contact@example.test",
            subject="Hello",
            body="This is a real send.",
            provider=provider,
        )
        assert message.direction == "outbound"
        assert message.is_internal_note is False
        assert len(provider.sent) == 1
        assert provider.sent[0].to == ("contact@example.test",)

        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert any(m.id == message.id for m in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_send_failure_does_not_record_a_message() -> None:
    """The module's own explicit guarantee: on provider failure, no
    `Message` row is created -- a failed send must never claim an email
    was sent that wasn't."""
    owner = make_user()
    agency, client, thread = _agency_client_thread_with_contact_email(owner.id)
    failing_provider = FakeEmailProvider(fail=True)
    try:
        with pytest.raises(EmailProviderError):
            send_email_message(
                owner.id,
                client.tenant_id,
                thread.id,
                to_email="contact@example.test",
                subject="Hello",
                body="This send will fail.",
                provider=failing_provider,
            )
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert listed == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cannot_send_email_on_thread_with_no_linked_contact() -> None:
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    contact = create_contact(owner.id, client.tenant_id, first_name="Will", last_name="Unlink")
    thread = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
    from product.crm.contacts import delete_contact

    delete_contact(owner.id, client.tenant_id, contact.id)
    provider = FakeEmailProvider()
    try:
        with pytest.raises(ConversationValidationError):
            send_email_message(
                owner.id,
                client.tenant_id,
                thread.id,
                to_email="whoever@example.test",
                subject="Hello",
                body="No contact linked anymore.",
                provider=provider,
            )
        assert provider.sent == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
