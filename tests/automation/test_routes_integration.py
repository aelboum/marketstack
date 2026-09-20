"""HTTP-level integration tests for product/automation/routes.py. Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_automation_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.get(f"/v1/automation/tenants/{uuid.uuid4()}/workflows")
    assert response.status_code == 401


def test_full_workflow_flow_over_http() -> None:
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

        create_resp = api.post(
            f"/v1/automation/tenants/{client_tenant_id}/workflows",
            json={
                "name": "Http workflow",
                "trigger_type": "crm.contact.created",
                "action_type": "create_task",
                "action_config": {"title": "Follow up"},
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        workflow_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "active"

        list_resp = api.get(f"/v1/automation/tenants/{client_tenant_id}/workflows", headers=headers)
        assert list_resp.status_code == 200
        assert any(w["id"] == workflow_id for w in list_resp.json())

        pause_resp = api.patch(
            f"/v1/automation/tenants/{client_tenant_id}/workflows/{workflow_id}/status",
            json={"status": "paused"},
            headers=headers,
        )
        assert pause_resp.status_code == 200
        assert pause_resp.json()["status"] == "paused"

        # Trigger the trigger event via a real CRM call over HTTP -- the
        # workflow is paused, so no run should be recorded.
        contact_resp = api.post(
            f"/v1/crm/tenants/{client_tenant_id}/contacts",
            json={"first_name": "Http", "last_name": "Contact"},
            headers=headers,
        )
        assert contact_resp.status_code == 201

        runs_resp = api.get(
            f"/v1/automation/tenants/{client_tenant_id}/workflows/{workflow_id}/runs",
            headers=headers,
        )
        assert runs_resp.status_code == 200
        assert runs_resp.json() == []

        delete_resp = api.delete(
            f"/v1/automation/tenants/{client_tenant_id}/workflows/{workflow_id}", headers=headers
        )
        assert delete_resp.status_code == 204
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_cross_agency_automation_access_over_http_is_non_enumerating_404() -> None:
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
            f"/v1/automation/tenants/{client_tenant_id}/workflows",
            json={
                "name": "Should fail",
                "trigger_type": "crm.contact.created",
                "action_type": "create_task",
                "action_config": {"title": "x"},
            },
            headers=stranger_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)
