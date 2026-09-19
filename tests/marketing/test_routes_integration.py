"""HTTP-level integration tests for product/marketing/routes.py, through
a real FastAPI TestClient and a real, already-migrated PostgreSQL
database. Marked `integration`, excluded from the default `pytest` run.

Mirrors tests/crm/test_routes_integration.py's own shape -- proves the
ingress-dependency choice and non-enumerating error mapping work
end-to-end through the real HTTP layer.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_marketing_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.post(
        f"/v1/marketing/tenants/{uuid.uuid4()}/campaigns",
        json={"name": "X", "channel": "email", "subject": "s", "body": "b"},
    )
    assert response.status_code == 401


def test_full_marketing_flow_over_http() -> None:
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

        contact_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/contacts",
            json={"first_name": "Http", "last_name": "Contact", "email": "http@ex.com"},
            headers=headers,
        )
        assert contact_resp.status_code == 201

        campaign_resp = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/campaigns",
            json={"name": "Http Campaign", "channel": "email", "subject": "Hi", "body": "Hello"},
            headers=headers,
        )
        assert campaign_resp.status_code == 201
        campaign_id = campaign_resp.json()["id"]
        assert campaign_resp.json()["status"] == "draft"

        list_resp = api.get(f"/v1/marketing/tenants/{client_tenant_id}/campaigns", headers=headers)
        assert list_resp.status_code == 200
        assert any(c["id"] == campaign_id for c in list_resp.json())

        send_resp = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/campaigns/{campaign_id}/send",
            headers=headers,
        )
        assert send_resp.status_code == 202
        assert send_resp.json()["recipient_count"] == 1

        recipients_resp = api.get(
            f"/v1/marketing/tenants/{client_tenant_id}/campaigns/{campaign_id}/recipients",
            headers=headers,
        )
        assert recipients_resp.status_code == 200
        assert len(recipients_resp.json()) == 1

        suppression_resp = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/suppressions",
            json={
                "contact_id": contact_resp.json()["id"],
                "channel": "sms",
                "reason": "manual",
            },
            headers=headers,
        )
        assert suppression_resp.status_code == 201
        suppression_list = api.get(
            f"/v1/marketing/tenants/{client_tenant_id}/suppressions", headers=headers
        )
        assert len(suppression_list.json()) == 1
        delete_resp = api.delete(
            f"/v1/marketing/tenants/{client_tenant_id}/suppressions/{suppression_resp.json()['id']}",
            headers=headers,
        )
        assert delete_resp.status_code == 204
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_cross_agency_marketing_access_over_http_is_non_enumerating_404() -> None:
    owner = make_user()
    stranger = make_user()
    api = TestClient(create_app())
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

        response = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/campaigns",
            json={"name": "Should Fail", "channel": "email", "subject": "s", "body": "b"},
            headers=stranger_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)


def test_oversized_campaign_body_rejected_with_clean_400() -> None:
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

        response = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/campaigns",
            json={
                "name": "Oversized",
                "channel": "email",
                "subject": "s",
                "body": "x" * 100_000,
            },
            headers=headers,
        )
        assert response.status_code == 422  # Pydantic max_length validation, not a DB error
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)
