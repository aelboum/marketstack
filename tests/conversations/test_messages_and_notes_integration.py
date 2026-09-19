"""Message CRUD, ordering, internal-note isolation, assignment, and
audit-metadata PII exclusion (docs/ROADMAP.md Phase 5.1, 5.5). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.identity import add_tenant_membership
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.errors import (
    ConversationAccessDeniedError,
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.messages import create_message, list_messages
from product.conversations.models import MAX_MESSAGE_BODY_LENGTH
from product.conversations.threads import assign_thread, create_thread
from product.crm.contacts import create_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_client_and_thread(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    contact = create_contact(owner_id, client.tenant_id, first_name="M", last_name="Sg")
    thread = create_thread(owner_id, client.tenant_id, contact_id=contact.id, channel="email")
    return agency, client, thread


def test_message_crud_and_sequence_ordering() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        m1 = create_message(
            owner.id,
            client.tenant_id,
            thread.id,
            direction="inbound",
            is_internal_note=False,
            body="first",
            author_user_id=None,
        )
        m2 = create_message(
            owner.id,
            client.tenant_id,
            thread.id,
            direction="outbound",
            is_internal_note=False,
            body="second",
            author_user_id=owner.id,
        )
        assert m2.sequence > m1.sequence

        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert [m.body for m in listed] == ["first", "second"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_direction_rejected() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        with pytest.raises(ConversationValidationError):
            create_message(
                owner.id,
                client.tenant_id,
                thread.id,
                direction="sideways",
                is_internal_note=False,
                body="x",
                author_user_id=owner.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_oversized_body_rejected() -> None:
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        too_long = "x" * (MAX_MESSAGE_BODY_LENGTH + 1)
        with pytest.raises(ConversationValidationError):
            create_message(
                owner.id,
                client.tenant_id,
                thread.id,
                direction="outbound",
                is_internal_note=False,
                body=too_long,
                author_user_id=owner.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_message_on_unknown_thread_fails_closed() -> None:
    owner = make_user()
    agency, client = provision_agency(owner.id, _name("agency")), None
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        with pytest.raises(ConversationReferenceNotFoundError):
            create_message(
                owner.id,
                client.tenant_id,
                uuid.uuid4(),
                direction="outbound",
                is_internal_note=False,
                body="x",
                author_user_id=owner.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_internal_note_never_reaches_the_email_send_path() -> None:
    """5.5's own named checkpoint requirement, proven structurally, not
    by convention: create_message(is_internal_note=True, ...) is called
    directly here -- product/conversations/email_sending.py::
    send_email_message() is never imported or called anywhere in this
    test, and create_message() itself (product/conversations/messages.py)
    contains no import of core.email/sms.py/whatsapp.py at all (grep the
    module's own imports -- confirmed by test_no_send_imports_in_messages_module
    below, a structural, not behavioral, proof)."""
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        note = create_message(
            owner.id,
            client.tenant_id,
            thread.id,
            direction="outbound",
            is_internal_note=True,
            body="internal only, never send this",
            author_user_id=owner.id,
        )
        assert note.is_internal_note is True
        # The note is recorded in the thread like any other message --
        # readable, but never sent (there is no code path that could send
        # it, proven separately below).
        listed = list_messages(owner.id, client.tenant_id, thread.id)
        assert any(m.id == note.id and m.is_internal_note for m in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_no_send_imports_in_messages_module() -> None:
    """Structural proof for the guarantee above: product/conversations
    /messages.py -- the ONLY function that writes a Message row -- has no
    ACTUAL IMPORT of core.email or the sms.py/whatsapp.py provider
    modules (checked via `ast`, not a raw substring search over the file
    -- a substring search would false-positive on this module's own
    docstring, which mentions `core.email` in prose while explaining
    exactly this guarantee; parsing real `import`/`from ... import`
    statements is what actually proves the code has no such dependency).
    If a future edit accidentally added one (e.g. "helpfully" auto-
    sending a message on create), this test's own import-graph check
    would fail, not silently keep passing while that coupling is
    introduced."""
    import ast

    import product.conversations.messages as messages_module

    source = open(messages_module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "core.email",
        "product.conversations.sms",
        "product.conversations.whatsapp",
    )
    violations = [m for m in imported_modules if any(m.startswith(p) for p in forbidden_prefixes)]
    assert violations == [], (
        f"product/conversations/messages.py must never import {violations} -- "
        "the internal-note isolation guarantee depends on this module having no "
        "send-capable code path at all."
    )


def test_assign_thread_to_real_member_succeeds() -> None:
    owner = make_user()
    member = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        add_tenant_membership(client.tenant_id, member.id)
        updated = assign_thread(owner.id, client.tenant_id, thread.id, member.id)
        assert updated.assigned_to_user_id == member.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_assign_thread_to_unrelated_user_fails_closed() -> None:
    """The real IDOR-adjacent check (product/conversations/threads.py
    ::assign_thread()'s own docstring): a syntactically valid, real
    user_id with NO membership anywhere in this tenant must be rejected,
    not silently assigned."""
    owner = make_user()
    unrelated = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        with pytest.raises(ConversationReferenceNotFoundError):
            assign_thread(owner.id, client.tenant_id, thread.id, unrelated.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_unauthorized_actor_cannot_assign_thread() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    try:
        with pytest.raises(ConversationAccessDeniedError):
            assign_thread(stranger.id, client.tenant_id, thread.id, owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_audit_metadata_never_contains_message_body_or_pii() -> None:
    """Personal-data requirement: message bodies/conversation contents
    must never land in audit metadata. Proven by reading the real,
    persisted core.audit_log row back -- not merely by not passing it in
    the code (a future edit could add it back; this test would catch
    that)."""
    owner = make_user()
    agency, client, thread = _agency_client_and_thread(owner.id)
    secret_body = "this body must never appear in the audit log: super-secret-marker-xyz"
    try:
        message = create_message(
            owner.id,
            client.tenant_id,
            thread.id,
            direction="outbound",
            is_internal_note=False,
            body=secret_body,
            author_user_id=owner.id,
        )
        entries = list_audit_log(
            client.tenant_id, resource_type="conversations.message", resource_id=str(message.id)
        )
        assert len(entries) >= 1
        for entry in entries:
            serialized_metadata = str(entry.metadata)
            assert secret_body not in serialized_metadata
            assert "super-secret-marker-xyz" not in serialized_metadata
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
