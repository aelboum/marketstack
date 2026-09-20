"""HTTP-level integration tests for product/telephony/routes.py, through
a real FastAPI TestClient and a real, already-migrated PostgreSQL
database. Marked `integration`, excluded from the default `pytest` run.

**Read-only routes only** -- see product/telephony/__init__.py's own
module docstring for why no write route exists. Data is created through
the service layer directly (mirroring how a real vendor integration or
admin tooling would populate it), then read back over real HTTP.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app
from product.telephony.calls import EVENT_CALL_INITIATED, receive_inbound_call_event
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_telephony_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.get(f"/v1/telephony/tenants/{uuid.uuid4()}/phone-numbers")
    assert response.status_code == 401


def test_full_telephony_read_flow_over_http() -> None:
    owner = make_user()
    api = TestClient(create_app())
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    agency_tenant_id = None
    client_tenant_id = None
    try:
        headers = _auth_headers(owner.id)
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])
        client_resp = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=headers,
        )
        client_tenant_id = uuid.UUID(client_resp.json()["tenant_id"])

        number = provision_phone_number(
            owner.id, client_tenant_id, country_code="US", provider=telephony_provider
        )
        body = b"payload"
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

        numbers_resp = api.get(
            f"/v1/telephony/tenants/{client_tenant_id}/phone-numbers", headers=headers
        )
        assert numbers_resp.status_code == 200
        assert any(n["id"] == str(number.id) for n in numbers_resp.json())

        number_resp = api.get(
            f"/v1/telephony/tenants/{client_tenant_id}/phone-numbers/{number.id}",
            headers=headers,
        )
        assert number_resp.status_code == 200
        assert number_resp.json()["phone_number"] == number.phone_number

        calls_resp = api.get(f"/v1/telephony/tenants/{client_tenant_id}/calls", headers=headers)
        assert calls_resp.status_code == 200
        assert any(c["id"] == str(call.id) for c in calls_resp.json())

        call_resp = api.get(
            f"/v1/telephony/tenants/{client_tenant_id}/calls/{call.id}", headers=headers
        )
        assert call_resp.status_code == 200
        assert call_resp.json()["status"] == "ringing"
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_cross_agency_telephony_access_over_http_is_non_enumerating_404() -> None:
    owner = make_user()
    stranger = make_user()
    api = TestClient(create_app())
    telephony_provider = FakeTelephonyProvider(webhook_secret="s")
    agency_tenant_id = None
    client_tenant_id = None
    try:
        owner_headers = _auth_headers(owner.id)
        stranger_headers = _auth_headers(stranger.id)

        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=owner_headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])
        client_resp = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=owner_headers,
        )
        client_tenant_id = uuid.UUID(client_resp.json()["tenant_id"])

        provision_phone_number(
            owner.id, client_tenant_id, country_code="US", provider=telephony_provider
        )

        response = api.get(
            f"/v1/telephony/tenants/{client_tenant_id}/phone-numbers", headers=stranger_headers
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)


def test_unknown_call_id_over_http_is_non_enumerating_404() -> None:
    owner = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    client_tenant_id = None
    try:
        headers = _auth_headers(owner.id)
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])
        client_resp = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=headers,
        )
        client_tenant_id = uuid.UUID(client_resp.json()["tenant_id"])

        response = api.get(
            f"/v1/telephony/tenants/{client_tenant_id}/calls/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == 404
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)
