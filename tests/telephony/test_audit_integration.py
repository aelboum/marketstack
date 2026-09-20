"""Proves telephony audit metadata never leaks a phone number, matching
this phase's own PII/audit discipline (docs/ROADMAP.md Phase 8, section
14) -- mirrors tests/appointments/test_reminders_integration.py::
test_audit_metadata_never_contains_contact_pii's own marker-based proof.
Real disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from product.agency.provisioning import provision_agency, provision_client
from product.telephony.calls import EVENT_CALL_INITIATED, receive_inbound_call_event
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"
_PII_PHONE_MARKER = "+15559990000"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_provision_number_audit_never_contains_the_phone_number() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        entries = list_audit_log(
            client.tenant_id, resource_type="telephony.phone_number", resource_id=str(number.id)
        )
        matching = [e for e in entries if e.action == "telephony.phone_number.provision"]
        assert len(matching) >= 1
        for entry in matching:
            assert number.phone_number not in str(entry.metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_inbound_call_event_audit_never_contains_the_caller_phone_number() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        body = b"payload"
        call = receive_inbound_call_event(
            provider=provider,
            headers={_HEADER: provider.compute_signature(body)},
            body=body,
            provider_event_id="evt-1",
            event_type=EVENT_CALL_INITIATED,
            to_number=number.phone_number,
            from_number=_PII_PHONE_MARKER,
            provider_call_id="pc-1",
        )
        assert call is not None
        entries = list_audit_log(
            client.tenant_id, resource_type="telephony.call", resource_id=str(call.id)
        )
        matching = [e for e in entries if e.action == "telephony.call.inbound_event"]
        assert len(matching) >= 1
        for entry in matching:
            assert _PII_PHONE_MARKER not in str(entry.metadata)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
