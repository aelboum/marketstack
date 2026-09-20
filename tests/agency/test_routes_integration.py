"""HTTP-level integration tests for product/agency/routes.py, through a
real FastAPI TestClient and a real, already-migrated PostgreSQL
database. Marked `integration`, excluded from the default `pytest` run.

Proves the ingress-dependency choice (docs/ADR/0002-...:
`get_current_actor`, never `get_tenant_context()`) and the shared
non-enumerating error mapping actually work end-to-end, not just at the
service layer tests/agency/test_isolation_integration.py already covers.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.api.main import create_app

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_request_is_401() -> None:
    client = TestClient(create_app())
    response = client.post("/v1/agency/agencies", json={"name": "Acme"})
    assert response.status_code == 401


def test_agency_signup_then_client_creation_then_listing_over_http() -> None:
    owner = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    client_tenant_id = None
    try:
        headers = _auth_headers(owner.id)

        create_agency_response = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        assert create_agency_response.status_code == 201
        agency_tenant_id = uuid.UUID(create_agency_response.json()["tenant_id"])

        create_client_response = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=headers,
        )
        assert create_client_response.status_code == 201
        client_tenant_id = uuid.UUID(create_client_response.json()["tenant_id"])

        list_response = api.get(f"/v1/agency/agencies/{agency_tenant_id}/clients", headers=headers)
        assert list_response.status_code == 200
        listed_ids = {c["tenant_id"] for c in list_response.json()}
        assert str(client_tenant_id) in listed_ids
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_invitation_accept_over_http_end_to_end() -> None:
    """POST /v1/agency/tenants/{tenant_id}/invitations/accept, real
    end-to-end (SaaS-OS commit `1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6`
    -- see docs/ADR/0002-...'s 'Resolved' note). Proves the route's own
    `tenant_id` path parameter, not just the service layer already
    covered by tests/agency/test_onboarding_integration.py."""
    owner = make_user()
    accepting_user = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    client_tenant_id = None
    try:
        owner_headers = _auth_headers(owner.id)
        accepting_headers = _auth_headers(accepting_user.id)

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

        invite_resp = api.post(
            f"/v1/agency/tenants/{client_tenant_id}/invitations",
            json={"invited_email": "new-member@example.com"},
            headers=owner_headers,
        )
        assert invite_resp.status_code == 201
        raw_token = invite_resp.json()["raw_token"]

        # Wrong tenant -- a real, existing tenant (the agency itself),
        # just not the one this token belongs to -- fails closed, 400.
        wrong_tenant_resp = api.post(
            f"/v1/agency/tenants/{agency_tenant_id}/invitations/accept",
            json={"raw_token": raw_token},
            headers=accepting_headers,
        )
        assert wrong_tenant_resp.status_code == 400

        accept_resp = api.post(
            f"/v1/agency/tenants/{client_tenant_id}/invitations/accept",
            json={"raw_token": raw_token},
            headers=accepting_headers,
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["tenant_id"] == str(client_tenant_id)

        # Already accepted -- second attempt fails closed too.
        replay_resp = api.post(
            f"/v1/agency/tenants/{client_tenant_id}/invitations/accept",
            json={"raw_token": raw_token},
            headers=accepting_headers,
        )
        assert replay_resp.status_code == 400
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, accepting_user.id)


def test_accepted_invitation_grants_the_real_starting_permissions_over_http() -> None:
    """The onboarding-role remediation's own behavior-level proof, at the
    HTTP layer: after a real accept over `/v1/agency/.../accept`, the new
    member can do something their starting `"member"` role should permit,
    and cannot do something it should not -- checked through
    `core.rbac.can()`, the platform's own real authorization chokepoint
    (never a database row inspected directly to "prove" this). Two
    distinct boundaries, both real:

    - within the starting role: CRM `contact` create/read/update, per
      `product/crm/event_handlers.py`'s own `_MEMBER_GRANTS` -- reactively
      granted the instant `accept_client_invitation()` provisions the
      "member" role, through the same `agency.role_provisioned` event
      Phase 4 already wired up (nothing new registered by this test);
    - outside it: CRM `contact` *delete* (deliberately withheld from
      `member`, same event-handler table) and this product's own
      `agency.client` `read` (owner-only, `roles.py
      ::_AGENCY_OWNER_CORE_PERMISSIONS`) -- a baseline member must not be
      able to list this agency's clients.
    """
    from core.rbac import can
    from product.crm.permissions import CONTACT_RESOURCE

    owner = make_user()
    accepting_user = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    client_tenant_id = None
    try:
        owner_headers = _auth_headers(owner.id)
        accepting_headers = _auth_headers(accepting_user.id)

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

        invite_resp = api.post(
            f"/v1/agency/tenants/{client_tenant_id}/invitations",
            json={"invited_email": "new-member@example.com"},
            headers=owner_headers,
        )
        raw_token = invite_resp.json()["raw_token"]

        accept_resp = api.post(
            f"/v1/agency/tenants/{client_tenant_id}/invitations/accept",
            json={"raw_token": raw_token},
            headers=accepting_headers,
        )
        assert accept_resp.status_code == 200

        # Allowed: within the starting "member" role.
        assert can(
            actor_id=accepting_user.id,
            tenant_id=client_tenant_id,
            action="read",
            resource=CONTACT_RESOURCE,
        )
        assert can(
            actor_id=accepting_user.id,
            tenant_id=client_tenant_id,
            action="create",
            resource=CONTACT_RESOURCE,
        )

        # Denied: deliberately outside it.
        assert not can(
            actor_id=accepting_user.id,
            tenant_id=client_tenant_id,
            action="delete",
            resource=CONTACT_RESOURCE,
        )
        assert not can(
            actor_id=accepting_user.id,
            tenant_id=client_tenant_id,
            action="read",
            resource="agency.client",
        )
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, accepting_user.id)


def test_cross_agency_access_over_http_is_non_enumerating_404() -> None:
    """docs/ADR/0002's own non-enumeration requirement, proven at the
    HTTP layer: an authenticated stranger to a real agency tenant gets
    the identical 404 shape api.errors.not_found() uses everywhere else
    in this platform -- never a 403, never a distinguishing message."""
    owner = make_user()
    stranger = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    try:
        owner_headers = _auth_headers(owner.id)
        stranger_headers = _auth_headers(stranger.id)

        create_response = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=owner_headers
        )
        agency_tenant_id = uuid.UUID(create_response.json()["tenant_id"])

        response = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("should-not-exist")},
            headers=stranger_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (agency_tenant_id,) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)
