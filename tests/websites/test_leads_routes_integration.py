"""HTTP-level integration tests for
`product/websites/routes.py::public_capture_lead_route()`/
`list_lead_submissions_route()` (docs/ROADMAP.md Phase 22). Real
disposable Postgres and, for the rate-limit test, real disposable Redis.
Marked `integration`, excluded from the default `pytest` run.
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


def _published_page_over_http(api, headers, tenant_id):
    website_slug = _name("lead-site")
    site_resp = api.post(
        f"/v1/websites/tenants/{tenant_id}/websites",
        json={"slug": website_slug, "name": "Lead Site"},
        headers=headers,
    )
    website_id = site_resp.json()["id"]
    page_slug = _name("home")
    page_resp = api.post(
        f"/v1/websites/tenants/{tenant_id}/websites/{website_id}/pages",
        json={"slug": page_slug, "title": "Home"},
        headers=headers,
    )
    page_id = page_resp.json()["id"]
    api.post(f"/v1/websites/tenants/{tenant_id}/pages/{page_id}/publish", headers=headers)
    return website_id, website_slug, page_slug


def test_capture_lead_over_http_returns_no_internal_identifiers() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        website_id, website_slug, page_slug = _published_page_over_http(
            api, headers, client.tenant_id
        )

        resp = api.post(
            f"/v1/websites/public/{website_slug}/{page_slug}/leads",
            json={
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "httplead@example.com",
                "idempotency_key": "http-key-1",
            },
        )
        assert resp.status_code == 201
        assert resp.json() == {"status": "received"}

        list_resp = api.get(
            f"/v1/websites/tenants/{client.tenant_id}/websites/{website_id}/leads",
            headers=headers,
        )
        assert list_resp.status_code == 200
        submissions = list_resp.json()
        assert len(submissions) == 1
        assert submissions[0]["email"] == "httplead@example.com"
        assert submissions[0]["contact_id"] is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_capture_lead_over_http_unknown_website_is_non_enumerating_404() -> None:
    api = TestClient(create_app())
    resp = api.post(
        "/v1/websites/public/totally-unknown-site/some-page/leads",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "x@example.com",
            "idempotency_key": "k",
        },
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "resource not found."}


def test_capture_lead_over_http_missing_required_field_is_400() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        headers = _auth_headers(owner.id)
        _website_id, website_slug, page_slug = _published_page_over_http(
            api, headers, client.tenant_id
        )
        resp = api.post(
            f"/v1/websites/public/{website_slug}/{page_slug}/leads",
            json={
                "first_name": "",
                "last_name": "Doe",
                "email": "x@example.com",
                "idempotency_key": "k",
            },
        )
        assert resp.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_lead_submissions_requires_authentication() -> None:
    api = TestClient(create_app())
    resp = api.get(f"/v1/websites/tenants/{uuid.uuid4()}/websites/{uuid.uuid4()}/leads")
    assert resp.status_code == 401


def test_capture_lead_over_http_is_rate_limited() -> None:
    from infra.ratelimit.config import get_ratelimit_config

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    old_value = os.environ.get("RATE_LIMIT_REQUESTS_PER_WINDOW")
    os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = "2"
    get_ratelimit_config.cache_clear()
    try:
        headers = _auth_headers(owner.id)
        api = TestClient(create_app())
        _website_id, website_slug, page_slug = _published_page_over_http(
            api, headers, client.tenant_id
        )

        statuses = []
        for i in range(4):
            resp = api.post(
                f"/v1/websites/public/{website_slug}/{page_slug}/leads",
                json={
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "email": f"rl{i}@example.com",
                    "idempotency_key": f"rl-key-{i}",
                },
            )
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
