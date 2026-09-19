"""HTTP-level integration tests for product/conversations/routes.py,
through a real FastAPI TestClient and a real, already-migrated PostgreSQL
database. Mirrors tests/crm/test_routes_integration.py's own shape.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_conversations_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.post(
        f"/v1/conversations/tenants/{uuid.uuid4()}/threads",
        json={"contact_id": str(uuid.uuid4()), "channel": "email"},
    )
    assert response.status_code == 401


def test_full_conversations_flow_over_http() -> None:
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
            json={"first_name": "HTTP", "last_name": "Contact"},
            headers=headers,
        )
        assert contact_resp.status_code == 201
        contact_id = contact_resp.json()["id"]

        thread_resp = api.post(
            f"/v1/conversations/tenants/{client_tenant_id}/threads",
            json={"contact_id": contact_id, "channel": "email"},
            headers=headers,
        )
        assert thread_resp.status_code == 201
        thread_id = thread_resp.json()["id"]
        assert thread_resp.json()["channel"] == "email"

        message_resp = api.post(
            f"/v1/conversations/tenants/{client_tenant_id}/threads/{thread_id}/messages",
            json={"direction": "outbound", "is_internal_note": True, "body": "an internal note"},
            headers=headers,
        )
        assert message_resp.status_code == 201
        assert message_resp.json()["is_internal_note"] is True

        list_resp = api.get(
            f"/v1/conversations/tenants/{client_tenant_id}/threads/{thread_id}/messages",
            headers=headers,
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        template_resp = api.post(
            f"/v1/conversations/tenants/{client_tenant_id}/templates",
            json={"name": _name("tpl"), "body": "Hello {name}"},
            headers=headers,
        )
        assert template_resp.status_code == 201

        list_threads_resp = api.get(
            f"/v1/conversations/tenants/{client_tenant_id}/threads", headers=headers
        )
        assert list_threads_resp.status_code == 200
        assert any(t["id"] == thread_id for t in list_threads_resp.json())
    finally:
        if client_tenant_id and agency_tenant_id:
            cleanup_tenant_tree(client_tenant_id, agency_tenant_id)
        cleanup_users(owner.id)


def test_cross_agency_conversations_access_over_http_is_non_enumerating_404() -> None:
    owner_a = make_user()
    owner_b = make_user()
    api = TestClient(create_app())
    agency_a_id = None
    client_a_id = None
    agency_b_id = None
    client_b_id = None
    try:
        headers_a = _auth_headers(owner_a.id)
        headers_b = _auth_headers(owner_b.id)

        agency_a_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency-a")}, headers=headers_a
        )
        agency_a_id = uuid.UUID(agency_a_resp.json()["tenant_id"])
        client_a_resp = api.post(
            f"/v1/agency/agencies/{agency_a_id}/clients",
            json={"name": _name("client-a")},
            headers=headers_a,
        )
        client_a_id = uuid.UUID(client_a_resp.json()["tenant_id"])

        agency_b_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency-b")}, headers=headers_b
        )
        agency_b_id = uuid.UUID(agency_b_resp.json()["tenant_id"])
        client_b_resp = api.post(
            f"/v1/agency/agencies/{agency_b_id}/clients",
            json={"name": _name("client-b")},
            headers=headers_b,
        )
        client_b_id = uuid.UUID(client_b_resp.json()["tenant_id"])

        contact_b_resp = api.post(
            f"/v1/crm/tenants/{client_b_id}/contacts",
            json={"first_name": "B", "last_name": "Only"},
            headers=headers_b,
        )
        contact_b_id = contact_b_resp.json()["id"]
        thread_b_resp = api.post(
            f"/v1/conversations/tenants/{client_b_id}/threads",
            json={"contact_id": contact_b_id, "channel": "email"},
            headers=headers_b,
        )
        thread_b_id = thread_b_resp.json()["id"]

        # owner_a, authenticated, has zero relationship to client_b's
        # tenant -- must get the identical non-enumerating 404 whether
        # the tenant/thread exists or not.
        cross_resp = api.get(
            f"/v1/conversations/tenants/{client_b_id}/threads/{thread_b_id}", headers=headers_a
        )
        assert cross_resp.status_code == 404
        unknown_resp = api.get(
            f"/v1/conversations/tenants/{uuid.uuid4()}/threads/{uuid.uuid4()}", headers=headers_a
        )
        assert unknown_resp.status_code == 404
        assert cross_resp.json() == unknown_resp.json()
    finally:
        if client_a_id and agency_a_id:
            cleanup_tenant_tree(client_a_id, agency_a_id)
        if client_b_id and agency_b_id:
            cleanup_tenant_tree(client_b_id, agency_b_id)
        cleanup_users(owner_a.id, owner_b.id)
