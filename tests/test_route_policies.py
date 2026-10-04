"""Every product route declares a route policy (saas-os docs/ADR/0030-
foundation-enforcement.md, FE-4).

`api/platform.py::_platform_lifespan` runs `assert_route_policies()` at
startup and refuses to serve any request if one route has no policy.
`tests/test_app_smoke.py` builds a `TestClient` without entering its
lifespan, so it never runs that check -- this test does, against the
fully composed app, so an undeclared route fails here instead of at
container startup.

The set of deliberately public product routes is pinned exactly: adding a
new unauthenticated route must be a visible change to this list, never a
side effect.
"""

from __future__ import annotations

from api.route_policy import RoutePolicyKind, assert_route_policies
from product.api.main import create_app

_EXPECTED_PRODUCT_PUBLIC_ROUTES = {
    "POST /v1/marketing/forms/{form_token}/submit",
    "GET /v1/marketing/track/open/{tracking_token}",
    "GET /v1/marketing/track/click/{tracking_token}",
    "POST /v1/appointments/book/{link_token}",
    "GET /v1/appointments/manage/{manage_token}",
    "POST /v1/appointments/manage/{manage_token}/cancel",
    "POST /v1/appointments/manage/{manage_token}/reschedule",
    "POST /v1/telephony/adapters/twilio/inbound-call",
    "POST /v1/telephony/adapters/twilio/transfer-events/{tenant_id}"
    "/{original_provider_call_id}/{attempt_id}",
    "GET /v1/websites/public/{website_slug}/{page_slug}",
    "POST /v1/websites/public/{website_slug}/{page_slug}/leads",
}


def test_every_route_declares_a_route_policy() -> None:
    assert_route_policies(create_app(), production=False)


def test_product_public_routes_are_exactly_the_expected_set() -> None:
    policies = assert_route_policies(create_app(), production=False)
    product_public = {
        label
        for label, policy in policies.items()
        if policy.kind is RoutePolicyKind.PUBLIC and label.split(" ", 1)[1].startswith("/v1/")
    }
    assert product_public == _EXPECTED_PRODUCT_PUBLIC_ROUTES
