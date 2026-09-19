"""HTTP-level integration tests for product/crm/routes.py, through a
real FastAPI TestClient and a real, already-migrated PostgreSQL
database. Marked `integration`, excluded from the default `pytest` run.

Mirrors tests/agency/test_routes_integration.py's own shape -- proves
the ingress-dependency choice and non-enumerating error mapping work
end-to-end through the real HTTP layer, not just the service layer
already covered by the other tests/crm/*_integration.py files.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_crm_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.post(
        f"/v1/crm/tenants/{uuid.uuid4()}/contacts", json={"first_name": "A", "last_name": "B"}
    )
    assert response.status_code == 401


def test_full_crm_flow_over_http() -> None:
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

        company_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/companies",
            json={"name": "Http Co"},
            headers=headers,
        )
        assert company_resp.status_code == 201
        company_id = company_resp.json()["id"]

        contact_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/contacts",
            json={"first_name": "Http", "last_name": "Contact", "company_id": company_id},
            headers=headers,
        )
        assert contact_resp.status_code == 201
        contact_id = contact_resp.json()["id"]

        pipeline_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/pipelines",
            json={"name": "Http Pipeline"},
            headers=headers,
        )
        pipeline_id = pipeline_resp.json()["id"]
        stage_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/pipelines/{pipeline_id}/stages",
            json={"name": "Open", "position": 0},
            headers=headers,
        )
        stage_id = stage_resp.json()["id"]

        opp_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/opportunities",
            json={
                "name": "Http Deal",
                "pipeline_id": pipeline_id,
                "stage_id": stage_id,
                "contact_id": contact_id,
                "amount_decimal": "500.00",
                "amount_currency": "USD",
            },
            headers=headers,
        )
        assert opp_resp.status_code == 201
        assert opp_resp.json()["amount"] == "500.00 USD"

        task_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/contacts/{contact_id}/tasks",
            json={"title": "Follow up"},
            headers=headers,
        )
        assert task_resp.status_code == 201

        activities_resp = api.get(
            f"/v1/crm/tenants/{client_tenant_id}/contacts/{contact_id}/activities", headers=headers
        )
        assert activities_resp.status_code == 200
        assert len(activities_resp.json()) == 1
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_cross_agency_crm_access_over_http_is_non_enumerating_404() -> None:
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
            f"/v1/crm/tenants/{client_tenant_id}/contacts",
            json={"first_name": "Should", "last_name": "Fail"},
            headers=stranger_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)
