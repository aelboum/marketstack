"""HTTP-level integration tests for product/websites/routes.py, through a
real FastAPI TestClient and a real, already-migrated PostgreSQL database
(docs/ROADMAP.md Phase 11.1). Marked `integration`, excluded from the
default `pytest` run.
"""

from __future__ import annotations

import os
import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app

from tests.websites._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


# --- Authentication ------------------------------------------------------------


def test_unauthenticated_websites_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.get(f"/v1/websites/tenants/{uuid.uuid4()}/websites")
    assert response.status_code == 401


# --- Full authenticated CRUD flow, website + page -----------------------------


def test_full_website_and_page_crud_flow_over_http() -> None:
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

        site_resp = api.post(
            f"/v1/websites/tenants/{client_tenant_id}/websites",
            json={"slug": _name("site"), "name": "HTTP Site"},
            headers=headers,
        )
        assert site_resp.status_code == 201
        website_id = site_resp.json()["id"]

        list_resp = api.get(f"/v1/websites/tenants/{client_tenant_id}/websites", headers=headers)
        assert list_resp.status_code == 200
        assert any(w["id"] == website_id for w in list_resp.json())

        get_resp = api.get(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}", headers=headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "HTTP Site"

        patch_resp = api.patch(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}",
            json={"name": "Renamed HTTP Site"},
            headers=headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "Renamed HTTP Site"

        page_resp = api.post(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}/pages",
            json={"slug": _name("home"), "title": "Home", "content_blocks": []},
            headers=headers,
        )
        assert page_resp.status_code == 201
        page_id = page_resp.json()["id"]
        assert page_resp.json()["status"] == "draft"

        page_list_resp = api.get(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}/pages",
            headers=headers,
        )
        assert page_list_resp.status_code == 200
        assert any(p["id"] == page_id for p in page_list_resp.json())

        page_patch_resp = api.patch(
            f"/v1/websites/tenants/{client_tenant_id}/pages/{page_id}",
            json={"content_blocks": [{"type": "paragraph", "text": "Hello"}]},
            headers=headers,
        )
        assert page_patch_resp.status_code == 200

        publish_resp = api.post(
            f"/v1/websites/tenants/{client_tenant_id}/pages/{page_id}/publish",
            headers=headers,
        )
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "published"

        unpublish_resp = api.post(
            f"/v1/websites/tenants/{client_tenant_id}/pages/{page_id}/unpublish",
            headers=headers,
        )
        assert unpublish_resp.status_code == 200
        assert unpublish_resp.json()["status"] == "draft"

        delete_page_resp = api.delete(
            f"/v1/websites/tenants/{client_tenant_id}/pages/{page_id}", headers=headers
        )
        assert delete_page_resp.status_code == 204

        delete_site_resp = api.delete(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}", headers=headers
        )
        assert delete_site_resp.status_code == 204
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


# --- Validation / conflict / not-found shapes ----------------------------------


def test_create_website_invalid_slug_over_http_returns_400() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": "Not A Slug!", "name": "Bad"},
            headers=headers,
        )
        assert resp.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_website_duplicate_slug_over_http_returns_409() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        slug = _name("dup")
        first = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": slug, "name": "First"},
            headers=headers,
        )
        assert first.status_code == 201
        second = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": slug, "name": "Second"},
            headers=headers,
        )
        assert second.status_code == 409
        # Fixed, generic detail -- never the raw exception text.
        assert second.json() == {"detail": "That slug or domain is already in use."}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_website_access_over_http_is_non_enumerating_404() -> None:
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

        site_resp = api.post(
            f"/v1/websites/tenants/{client_tenant_id}/websites",
            json={"slug": _name("site"), "name": "Owner Only"},
            headers=owner_headers,
        )
        website_id = site_resp.json()["id"]

        response = api.get(
            f"/v1/websites/tenants/{client_tenant_id}/websites/{website_id}",
            headers=stranger_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id, stranger.id)


def test_unknown_website_id_over_http_is_non_enumerating_404() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        resp = api.get(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{uuid.uuid4()}", headers=headers
        )
        assert resp.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_website_clear_custom_domain_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        create_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={
                "slug": _name("site"),
                "name": "Domained",
                "custom_domain": f"{_name('example')}.com",
            },
            headers=headers,
        )
        website_id = create_resp.json()["id"]
        assert create_resp.json()["custom_domain"] is not None

        clear_resp = api.patch(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{website_id}",
            json={"clear_custom_domain": True},
            headers=headers,
        )
        assert clear_resp.status_code == 200
        assert clear_resp.json()["custom_domain"] is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Public, unauthenticated page-render route ---------------------------------


def test_public_page_route_returns_published_content_and_branding() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        website_slug = _name("public-site")
        site_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": website_slug, "name": "Public Site"},
            headers=headers,
        )
        website_id = site_resp.json()["id"]

        page_slug = _name("home")
        blocks = [{"type": "heading", "text": "Hello World", "level": 1}]
        page_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{website_id}/pages",
            json={"slug": page_slug, "title": "Home", "content_blocks": blocks},
            headers=headers,
        )
        page_id = page_resp.json()["id"]
        api.post(
            f"/v1/websites/tenants/{client.tenant_id}/pages/{page_id}/publish", headers=headers
        )

        public_resp = api.get(f"/v1/websites/public/{website_slug}/{page_slug}")
        assert public_resp.status_code == 200
        body = public_resp.json()
        assert body["title"] == "Home"
        assert body["content_blocks"] == blocks
        assert "branding" in body
        assert "display_name" in body["branding"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_public_page_route_unknown_website_slug_is_non_enumerating_404() -> None:
    api = TestClient(create_app())
    resp = api.get("/v1/websites/public/totally-unknown-site/some-page")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "resource not found."}


def test_public_page_route_draft_page_is_non_enumerating_404() -> None:
    """A page that exists but was never published is not reachable
    through the public route -- returns the identical 404 shape as an
    unknown page, never leaking that it exists as a draft."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        website_slug = _name("draft-site")
        site_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": website_slug, "name": "Draft Site"},
            headers=headers,
        )
        website_id = site_resp.json()["id"]
        page_slug = _name("unpublished")
        api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{website_id}/pages",
            json={"slug": page_slug, "title": "Draft Page"},
            headers=headers,
        )

        resp = api.get(f"/v1/websites/public/{website_slug}/{page_slug}")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "resource not found."}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_public_page_route_rate_limited() -> None:
    from infra.ratelimit.config import get_ratelimit_config

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    old_value = os.environ.get("RATE_LIMIT_REQUESTS_PER_WINDOW")
    os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = "2"
    get_ratelimit_config.cache_clear()
    try:
        headers = _auth_headers(owner.id)
        website_slug = _name("rl-site")
        api = TestClient(create_app())
        site_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites",
            json={"slug": website_slug, "name": "RL Site"},
            headers=headers,
        )
        website_id = site_resp.json()["id"]
        page_slug = _name("home")
        page_resp = api.post(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{website_id}/pages",
            json={"slug": page_slug, "title": "Home"},
            headers=headers,
        )
        page_id = page_resp.json()["id"]
        api.post(
            f"/v1/websites/tenants/{client.tenant_id}/pages/{page_id}/publish", headers=headers
        )

        statuses = []
        for _ in range(4):
            resp = api.get(f"/v1/websites/public/{website_slug}/{page_slug}")
            statuses.append(resp.status_code)
        assert 429 in statuses, statuses
    finally:
        if old_value is None:
            os.environ.pop("RATE_LIMIT_REQUESTS_PER_WINDOW", None)
        else:
            os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = old_value
        get_ratelimit_config.cache_clear()
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
