"""Call recording metadata, storage, retention enforcement, and the
separate `call_recording` RBAC resource (docs/ROADMAP.md Phase 8.3). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.foundation.storage import FakeObjectStorage, ObjectNotFoundError
from product.telephony.calls import EVENT_CALL_INITIATED, receive_inbound_call_event
from product.telephony.errors import TelephonyAccessDeniedError, TelephonyReferenceNotFoundError
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import FakeTelephonyProvider
from product.telephony.recordings import (
    get_call_recording,
    purge_expired_recordings,
    store_call_recording,
)

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"


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


def test_store_get_call_recording_round_trip() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    storage = FakeObjectStorage()
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=telephony_provider
        )
        body = b"webhook-body"
        call = receive_inbound_call_event(
            provider=telephony_provider,
            headers={_HEADER: telephony_provider.compute_signature(body)},
            body=body,
            provider_event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            from_number="+15551234567",
            provider_call_id="pc-1",
        )
        assert call is not None

        stored = store_call_recording(
            owner.id,
            client.tenant_id,
            call.id,
            data=b"fake-audio-bytes",
            duration_seconds=42,
            retention_expires_at=datetime.now(UTC) + timedelta(days=30),
            storage=storage,
        )
        assert stored.call_id == call.id

        fetched_view, data = get_call_recording(
            owner.id, client.tenant_id, stored.id, storage=storage
        )
        assert fetched_view.id == stored.id
        assert data == b"fake-audio-bytes"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_store_recording_for_unknown_call_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    storage = FakeObjectStorage()
    try:
        with pytest.raises(TelephonyReferenceNotFoundError):
            store_call_recording(
                owner.id,
                client.tenant_id,
                uuid.uuid4(),
                data=b"x",
                duration_seconds=1,
                retention_expires_at=datetime.now(UTC) + timedelta(days=1),
                storage=storage,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_member_role_cannot_access_call_recordings() -> None:
    """`telephony.call_recording` is granted to `owner` only, never
    `member` -- see product/telephony/event_handlers.py's own docstring.
    A member with full telephony.call access must still be denied here."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    storage = FakeObjectStorage()
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=telephony_provider
        )
        body = b"webhook-body"
        call = receive_inbound_call_event(
            provider=telephony_provider,
            headers={_HEADER: telephony_provider.compute_signature(body)},
            body=body,
            provider_event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            from_number="+15551234567",
            provider_call_id="pc-1",
        )
        assert call is not None
        with pytest.raises(TelephonyAccessDeniedError):
            store_call_recording(
                member.id,
                client.tenant_id,
                call.id,
                data=b"x",
                duration_seconds=1,
                retention_expires_at=datetime.now(UTC) + timedelta(days=1),
                storage=storage,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_purge_expired_recordings_deletes_object_and_row() -> None:
    """Retention is mandatory: a recording past its retention window is
    actually deleted (object + metadata row), not just hidden."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    storage = FakeObjectStorage()
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=telephony_provider
        )
        body = b"webhook-body"
        call = receive_inbound_call_event(
            provider=telephony_provider,
            headers={_HEADER: telephony_provider.compute_signature(body)},
            body=body,
            provider_event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            from_number="+15551234567",
            provider_call_id="pc-1",
        )
        assert call is not None
        now = datetime.now(UTC)
        expired = store_call_recording(
            owner.id,
            client.tenant_id,
            call.id,
            data=b"expired-audio",
            duration_seconds=10,
            retention_expires_at=now - timedelta(days=1),
            storage=storage,
        )
        not_yet_expired = store_call_recording(
            owner.id,
            client.tenant_id,
            call.id,
            data=b"fresh-audio",
            duration_seconds=10,
            retention_expires_at=now + timedelta(days=30),
            storage=storage,
        )

        purged_count = purge_expired_recordings(client.tenant_id, storage=storage, now=now)
        assert purged_count == 1

        with pytest.raises(ObjectNotFoundError):
            storage.get_object(expired.storage_key)
        assert storage.get_object(not_yet_expired.storage_key) == b"fresh-audio"

        with pytest.raises(TelephonyReferenceNotFoundError):
            get_call_recording(owner.id, client.tenant_id, expired.id, storage=storage)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
