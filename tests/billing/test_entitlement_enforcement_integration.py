"""Focused integration tests for the SaaS entitlement-enforcement
follow-up (`product/billing/resale_plans.py::create_resale_plan()`'s own
module docstring): the one production integration point where this
product first calls the already-built, already-tested SaaS-OS mechanisms
`core.billing.require_entitlement()` (boolean capability gate) and
`core.usage.consume_quota()` (atomic numeric quota gate).

Every other `tests/billing/*_integration.py` file already proves RBAC,
tenant isolation, and the pre-existing resale-tier ceiling check work
correctly with these two new checks in place (their own fixtures were
updated to satisfy the new `reseller_enabled` precondition, nothing about
their own assertions changed). This file proves the entitlement/quota
checks themselves: allowed, not-entitled, missing-key semantics (which
differ, by design, between the boolean and numeric mechanisms -- see
below), limit-exceeded, RBAC composition, and cross-tenant isolation.

Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.billing import EntitlementDeniedError, create_plan, subscribe
from core.billing.provider import FakeBillingProvider
from core.identity import add_tenant_membership
from core.identity.sessions import issue_session
from core.rbac import RoleScope, assign_role
from core.usage import QuotaExceededError
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.api.main import create_app
from product.billing.errors import BillingAccessDeniedError
from product.billing.resale_plans import (
    RESALE_PLAN_CREATION_QUOTA_METRIC,
    RESELLER_ENABLED_ENTITLEMENT_KEY,
    create_resale_plan,
    list_resale_plans,
)

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


def _subscribe_agency(owner_id, agency_tenant_id, entitlements: dict) -> str:
    plan_key = _name("platform-plan")
    create_plan(plan_key, "Throwaway Platform Plan", entitlements=entitlements)
    subscribe(agency_tenant_id, plan_key, provider=FakeBillingProvider(), actor_user_id=owner_id)
    return plan_key


def _create(owner_id, tenant_id, *, key: str | None = None):
    return create_resale_plan(
        owner_id,
        tenant_id,
        key=key or _name("tier"),
        name="Tier",
        price_amount=0,
        price_currency="USD",
    )


# --- Boolean capability gate: allowed / not-entitled / missing-key ----------------


def test_tenant_with_capability_entitlement_is_allowed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id, agency.tenant_id, {RESELLER_ENABLED_ENTITLEMENT_KEY: True}
    )
    plan_keys = [platform_key]
    try:
        plan = _create(owner.id, agency.tenant_id)
        plan_keys.append(plan.underlying_plan_key)
        assert plan.tenant_id == agency.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


def test_tenant_without_capability_entitlement_is_denied() -> None:
    """The key is present but explicitly `False` -- not merely absent
    (the next test covers absence) -- still denied."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id, agency.tenant_id, {RESELLER_ENABLED_ENTITLEMENT_KEY: False}
    )
    try:
        with pytest.raises(EntitlementDeniedError):
            _create(owner.id, agency.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key)


def test_tenant_with_no_subscription_at_all_is_denied_the_capability() -> None:
    """`core.billing.get_entitlements()`'s own "no active subscription ->
    `{}`" default composed with `has_entitlement()`'s own "absent means
    denied" default (`core/billing/service.py::has_entitlement()`'s own
    docstring) -- a tenant that has never subscribed to anything is not
    silently entitled to resell. This is the OPPOSITE default from the
    numeric quota gate below (see
    `test_missing_numeric_quota_configuration_is_unlimited_not_denied`) --
    both are the repository's own, deliberate, already-documented
    conventions for their respective entitlement TYPE, not a choice this
    phase invents."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(EntitlementDeniedError):
            _create(owner.id, agency.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Numeric quota gate: allowed / limit-exceeded / missing-key -------------------


def test_numeric_quota_allows_creation_within_configured_limit() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id,
        agency.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 2},
    )
    plan_keys = [platform_key]
    try:
        first = _create(owner.id, agency.tenant_id, key="first")
        second = _create(owner.id, agency.tenant_id, key="second")
        plan_keys += [first.underlying_plan_key, second.underlying_plan_key]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


def test_numeric_quota_rejects_creation_exceeding_configured_limit() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id,
        agency.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 1},
    )
    plan_keys = [platform_key]
    try:
        first = _create(owner.id, agency.tenant_id, key="first")
        plan_keys.append(first.underlying_plan_key)
        with pytest.raises(QuotaExceededError):
            _create(owner.id, agency.tenant_id, key="second")
        # Denied atomically, never partially -- no second row was created,
        # and a subsequent read of the reseller's own catalog still shows
        # exactly the one plan that actually succeeded.
        assert len(list_resale_plans(owner.id, agency.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


def test_missing_numeric_quota_configuration_is_unlimited_not_denied() -> None:
    """`core.usage.service._numeric_limit()`'s own documented, deliberate
    convention: an entitlements dict with no configured value at all for
    `RESALE_PLAN_CREATION_QUOTA_METRIC` means "no limit," not "limit of
    zero" -- the opposite default from the boolean gate above, by design
    (a capability flag's absence means "may this happen at all" -> deny;
    a metered quota's absence means "how much may happen" -> nothing
    configured -> unbounded on that one dimension). Verified here directly
    rather than merely asserted in a docstring: creating three plans with
    no quota key configured succeeds every time."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id, agency.tenant_id, {RESELLER_ENABLED_ENTITLEMENT_KEY: True}
    )
    plan_keys = [platform_key]
    try:
        for i in range(3):
            plan = _create(owner.id, agency.tenant_id, key=f"tier-{i}")
            plan_keys.append(plan.underlying_plan_key)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


# --- RBAC + entitlement composition ------------------------------------------------


def test_rbac_denial_is_enforced_even_when_the_tenant_is_fully_entitled() -> None:
    """A `member` (read-only on the resale catalog,
    `product/billing/event_handlers.py`'s own grant split) is denied by
    RBAC even though the tenant itself holds every entitlement this
    operation checks -- entitlement approval never substitutes for, or
    bypasses, the pre-existing RBAC chokepoint (`product.billing
    .permissions.require()`, called first, unchanged)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    membership = add_tenant_membership(
        agency.tenant_id, member.id, caller=SystemCaller(SystemAuthority.PROVISIONING)
    )
    member_role = ensure_client_member_role(agency.tenant_id)
    assign_role(
        agency.tenant_id,
        membership.id,
        member_role.id,
        scope=RoleScope.SELF,
        caller=UserCaller(owner.id),
    )
    platform_key = _subscribe_agency(
        owner.id,
        agency.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 100},
    )
    try:
        with pytest.raises(BillingAccessDeniedError):
            _create(member.id, agency.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)
        cleanup_global_plan_keys(platform_key)


# --- Cross-tenant isolation ---------------------------------------------------------


def test_cross_tenant_entitlement_cannot_authorize_a_different_tenant() -> None:
    """Agency A is fully entitled to resell; Agency B (a separate,
    unrelated tenant/owner) is not. Agency B's own owner is still denied
    -- `core.billing.get_entitlements()` is evaluated against the literal
    target `tenant_id`, never a sibling or any other tenant."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    platform_key_a = _subscribe_agency(
        owner_a.id, agency_a.tenant_id, {RESELLER_ENABLED_ENTITLEMENT_KEY: True}
    )
    try:
        with pytest.raises(EntitlementDeniedError):
            _create(owner_b.id, agency_b.tenant_id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
        cleanup_global_plan_keys(platform_key_a)


def test_cross_tenant_quota_consumption_does_not_affect_a_different_tenant() -> None:
    """Agency A exhausts its own quota of 1; Agency B, with the identical
    limit, is completely unaffected -- `core.usage.consume_quota()`'s own
    advisory lock and usage read are both keyed on `(tenant_id, metric)`,
    never shared across tenants."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    platform_key_a = _subscribe_agency(
        owner_a.id,
        agency_a.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 1},
    )
    platform_key_b = _subscribe_agency(
        owner_b.id,
        agency_b.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 1},
    )
    plan_keys = [platform_key_a, platform_key_b]
    try:
        plan_a = _create(owner_a.id, agency_a.tenant_id)
        plan_keys.append(plan_a.underlying_plan_key)
        with pytest.raises(QuotaExceededError):
            _create(owner_a.id, agency_a.tenant_id, key="second")

        # Agency B's own, separate quota is untouched by Agency A's usage.
        plan_b = _create(owner_b.id, agency_b.tenant_id)
        plan_keys.append(plan_b.underlying_plan_key)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
        cleanup_global_plan_keys(*plan_keys)


# --- API behavior --------------------------------------------------------------------


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_entitlement_denial_over_http_returns_403_not_entitled_never_400() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(owner.id),
            json={
                "key": _name("tier"),
                "name": "Tier",
                "price_amount": 0,
                "price_currency": "USD",
            },
        )
        assert response.status_code == 403
        # Fixed, generic detail -- never the entitlement key or any
        # billing-internal detail (product/billing/routes.py's own module
        # docstring).
        assert "entitlement" not in response.json()["detail"].lower()
        assert RESELLER_ENABLED_ENTITLEMENT_KEY not in response.text
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_quota_denial_over_http_returns_429() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _subscribe_agency(
        owner.id,
        agency.tenant_id,
        {RESELLER_ENABLED_ENTITLEMENT_KEY: True, RESALE_PLAN_CREATION_QUOTA_METRIC: 1},
    )
    plan_keys = [platform_key]
    try:
        api = TestClient(create_app())
        body = {
            "name": "Tier",
            "price_amount": 0,
            "price_currency": "USD",
        }
        first = api.post(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(owner.id),
            json={"key": _name("first"), **body},
        )
        assert first.status_code == 201
        plan_keys.append(f"resale:{first.json()['id']}")

        second = api.post(
            f"/v1/billing/tenants/{agency.tenant_id}/resale-plans",
            headers=_auth_headers(owner.id),
            json={"key": _name("second"), **body},
        )
        assert second.status_code == 429
        assert RESALE_PLAN_CREATION_QUOTA_METRIC not in second.text
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)
