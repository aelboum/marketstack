"""HTTP-level integration tests for `product/billing/routes.py`, through a
real FastAPI `TestClient` and a real, already-migrated PostgreSQL database
(docs/ROADMAP.md Phase 13 API exposure follow-up). Mirrors
`tests/accounting/test_routes_integration.py`'s own shape.

Every existing `tests/billing/*_integration.py` test exercises
`product/billing/{resale_plans,subscriptions}.py` directly, at the service
layer -- proving the underlying logic works, but never that
`product/billing/routes.py::router` is actually reachable through the
running application (`product/api/main.py::create_app()`). This file
closes exactly that gap: real HTTP requests, through the real router, the
real `get_current_actor` authentication dependency, and the real
`product.billing.permissions.require()` -> `core.rbac.can()` chokepoint --
no new authorization semantics, nothing bypassed.

**Subscription/plan-change/cancel routes are deliberately NOT exercised
here**: `create_platform_subscription()`/`create_resale_subscription()`
call `core.billing.subscribe_idempotent()`, which resolves a real
`StripeBillingProvider` when no `provider` override is supplied -- and
`product/billing/routes.py` never exposes a `provider` override over HTTP
(by design: a caller cannot choose their own payment provider). Exercising
subscription *creation* over HTTP would therefore require real Stripe
credentials, which is a pre-existing billing-implementation constraint,
not a router-wiring one, and out of this phase's scope (no Stripe
changes). The read-only subscription/entitlement routes need no provider
at all and are exercised below -- including as this file's own proof that
the existing Agency -> Client `SUBTREE` reach still works through the
newly-mounted HTTP layer, exactly as it already does at the service layer.

Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.billing import create_plan, subscribe
from core.billing.provider import FakeBillingProvider
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.billing.resale_plans import RESELLER_ENABLED_ENTITLEMENT_KEY
from product.billing.subscriptions import create_platform_subscription

from tests.billing._cleanup import (
    cleanup_global_plan_keys,
    cleanup_tenant_tree,
    cleanup_users,
    make_user,
)

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


def _give_agency_a_platform_subscription(owner_id, agency_tenant_id, entitlements: dict) -> str:
    """Sets up the reseller's own entitlement ceiling for a resale-plan
    creation test -- via `core.billing.subscribe()` directly (never HTTP;
    see module docstring for why subscription creation is not exercised
    over HTTP in this file). Returns the plan key, for cleanup.

    Always also grants `RESELLER_ENABLED_ENTITLEMENT_KEY` -- SaaS
    entitlement enforcement's own boolean capability gate
    (`product/billing/resale_plans.py::create_resale_plan()`'s own module
    docstring), a precondition this file's own resale-plan-creation test
    needs regardless of the ceiling values under test."""
    plan_key = _name("platform-plan")
    create_plan(
        plan_key,
        "Throwaway Platform Plan",
        entitlements={**entitlements, RESELLER_ENABLED_ENTITLEMENT_KEY: True},
    )
    subscribe(agency_tenant_id, plan_key, provider=FakeBillingProvider(), actor_user_id=owner_id)
    return plan_key


# --- Route availability -------------------------------------------------------------


def test_billing_router_is_mounted() -> None:
    """`product/api/main.py::create_app()` actually includes
    `product/billing/routes.py::router` -- proven by asking the running
    application itself (its own OpenAPI schema), not by re-reading the
    source. `GET /v1/billing/plans` (no tenant context) is gone (B2B2C
    API Contract Expansion, Step 5) -- replaced by the explicit, tenant-
    scoped `GET /tenants/{tenant_id}/plans` below, mirroring
    `tests/accounting/test_api_routes_integration.py`'s own
    (method, path) set-membership style."""
    schema = create_app().openapi()
    paths = schema["paths"]
    assert "/v1/billing/plans" not in paths
    expected = {
        ("get", "/v1/billing/tenants/{tenant_id}/plans"),
        ("get", "/v1/billing/tenants/{tenant_id}/billing-accounts"),
        ("post", "/v1/billing/tenants/{tenant_id}/commercial-subscriptions"),
        ("get", "/v1/billing/tenants/{tenant_id}/commercial-subscriptions/{subscription_id}"),
        ("get", "/v1/billing/tenants/{tenant_id}/resale-plans"),
        ("get", "/v1/billing/tenants/{tenant_id}/subscriptions"),
    }
    for method, path in expected:
        assert path in paths, path
        assert method in paths[path], (method, path)


# --- GET /v1/billing/tenants/{tenant_id}/plans (explicit catalog context, Step 5) -----


def test_unauthenticated_plans_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.get(f"/v1/billing/tenants/{uuid.uuid4()}/plans")
    assert response.status_code == 401


def test_authorized_tenant_lists_its_own_eligible_catalog_over_http() -> None:
    """Replaces `test_list_platform_plans_route_returns_the_existing
    _contract` (B2B2C API Contract Expansion, Step 5) -- same underlying
    behavioral guarantee ("an authenticated caller can see the plans it
    may self-serve"), now through the real, explicit, tenant-scoped
    contract instead of the old unrestricted, tenant-agnostic one Catalog
    v2 does not support. Adoption happens at the service layer
    (`create_platform_subscription()`), never over HTTP -- module
    docstring's own "subscription creation needs a real Stripe provider"
    reasoning applies identically here."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    plan_key = _name("plan")
    create_plan(plan_key, "Test Plan", entitlements={"max_users": 5})
    try:
        create_platform_subscription(
            owner.id, agency.tenant_id, plan_key, _name("idem"), provider=FakeBillingProvider()
        )
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/plans", headers=_auth_headers(owner.id)
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        matching = [row for row in body if row["key"] == plan_key]
        assert len(matching) == 1
        plan = matching[0]
        assert plan["name"] == "Test Plan"
        assert plan["entitlements"] == {"max_users": 5}
        assert plan["owner_tenant_id"] == str(agency.tenant_id)
        assert plan["visibility"] == "public"
        assert plan["status"] == "active"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(plan_key)


def test_unrelated_actor_cannot_list_an_unrelated_tenants_catalog_over_http() -> None:
    """Attack 4 (catalog enumeration): supplying an arbitrary tenant id
    the caller has no role at all is denied, never a silently empty
    `[]` -- a non-enumerating `404`, the same shape every other
    cross-tenant denial in this router already has."""
    owner_a = make_user()
    stranger = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency_a.tenant_id}/plans", headers=_auth_headers(stranger.id)
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, stranger.id)


# --- Resale plans: authentication, permission enforcement, tenant isolation -----------


def test_unauthenticated_resale_plans_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.get(f"/v1/billing/tenants/{uuid.uuid4()}/resale-plans")
    assert response.status_code == 401


def test_agency_owner_can_create_and_list_its_own_resale_plan_over_http() -> None:
    """Proves the router reaches the real permission layer and the real
    service functions end to end: `provision_agency()`'s owner role only
    gains `billing.resale_plan` permissions because
    `product/billing/event_handlers.py` is now imported (for its
    `agency.role_provisioned` subscription) by `product/api/main.py` --
    the exact gap this phase's wiring closes."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 50}
    )
    resale_key = _name("starter")
    resale_plan_id: str | None = None
    try:
        api = TestClient(create_app())
        create_response = api.post(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(owner.id),
            json={
                "key": resale_key,
                "name": "Starter",
                "price_amount": 1999,
                "price_currency": "usd",
                "entitlements": {"max_users": 10},
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        resale_plan_id = created["id"]
        assert created["key"] == resale_key
        assert created["tenant_id"] == str(agency.tenant_id)

        list_response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(owner.id),
        )
        assert list_response.status_code == 200
        assert any(row["id"] == created["id"] for row in list_response.json())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        plan_keys_to_clean = [platform_key]
        if resale_plan_id is not None:
            plan_keys_to_clean.append(f"resale:{resale_plan_id}")
        cleanup_global_plan_keys(*plan_keys_to_clean)
        cleanup_users(owner.id)


def test_cross_agency_resale_plans_request_over_http_is_non_enumerating_404() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency_b.tenant_id}/resale-plans",
            headers=_auth_headers(owner_a.id),
        )
        # Non-enumerating: the same generic 404 as a genuinely unknown
        # resource, never a distinguishable "403 forbidden" that would leak
        # agency_b's existence to an unrelated caller.
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_unrelated_actor_cannot_read_resale_plans_over_http() -> None:
    """A real, authenticated actor with no membership anywhere near this
    agency still gets the same non-enumerating 404 -- proves the route
    reaches `core.rbac.can()`, never merely checking that a caller is
    *some* authenticated user."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    stranger = make_user()
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(stranger.id),
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


# --- Agency -> Client SUBTREE reach, preserved through the HTTP layer -----------------


def test_agency_owner_subtree_reaches_its_clients_subscriptions_over_http() -> None:
    """Read-only, provider-free routes (module docstring) -- an empty list
    is still a `200`, not a `404`: the agency owner's pre-existing
    `SUBTREE` role reaches the client tenant's `billing.subscription`
    resource with zero extra grant, exactly as it already does for every
    other product module's own client-scoped resources."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{client.tenant_id}/subscriptions",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 200
        assert response.json() == []

        entitlements_response = api.get(
            f"/v1/billing/tenants/{client.tenant_id}/entitlements",
            headers=_auth_headers(owner.id),
        )
        assert entitlements_response.status_code == 200
        assert entitlements_response.json() == {}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_read_a_clients_subscriptions_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    stranger = make_user()
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{client.tenant_id}/subscriptions",
            headers=_auth_headers(stranger.id),
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)
