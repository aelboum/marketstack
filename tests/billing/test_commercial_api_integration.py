"""HTTP-level integration tests for the B2B2C commercial API surface
(docs/ROADMAP.md Phase 17, Step 5): `GET /tenants/{tenant_id}
/billing-accounts`, `POST`/`GET /tenants/{tenant_id}
/commercial-subscriptions[/{subscription_id}]`. Real FastAPI `TestClient`,
real disposable PostgreSQL. Mirrors `tests/billing
/test_routes_integration.py`'s own shape and module docstring reasoning
(real HTTP requests, through the real router, the real `get_current_actor`
dependency, nothing bypassed) -- kept in its own file rather than added to
that one because every test here needs a real, `active` merchant (the
`provider="fake"` test double `tests/billing
/test_commercial_subscriptions_integration.py` and `tests/billing
/test_catalog_integration.py` both already establish), which that file's
own existing tests deliberately avoid needing.

Covers the Step 5 task's own required test matrix: self-pay and sponsored
commercial subscriptions over HTTP, BillingAccount representation and
isolation, retrieval, and all six named security/authorization attacks
(section 15).

**Creation success/idempotency over HTTP is genuinely not exercisable in
this environment** -- see the "Commercial subscriptions: wiring, through
to the provider boundary" section's own comment below for the full,
pre-existing reason (no Stripe Connect, no configured `STRIPE_API_KEY`,
and the route deliberately accepts no `provider` override). Those
guarantees are proven at the service layer instead, against the
identical, unchanged function this route calls
(`tests/billing/test_commercial_subscriptions_integration.py`,
`tests/billing/test_catalog_integration.py`).

Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.authority import SystemAuthority, SystemCaller
from core.billing import MerchantAccountStatus, PlanVisibility, create_merchant_account
from core.billing.provider import FakeBillingProvider
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.agency.onboarding import accept_client_invitation, invite_client_member
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.billing.catalog import create_owned_plan, create_plan_offer
from product.billing.commercial_subscriptions import create_commercial_subscription
from product.billing.parties import get_or_create_billing_account

from tests.billing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_SYSTEM = SystemCaller(SystemAuthority.BILLING_OPERATIONS)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _agency_with_active_merchant(owner_id: uuid.UUID, prefix: str = "agency"):
    agency = provision_agency(owner_id, _name(prefix))
    merchant = create_merchant_account(
        _SYSTEM,
        agency.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    return agency, merchant


def _billing_account_id(payer_tenant_id: uuid.UUID, *, merchant_tenant_id, merchant_account_id):
    view, _created = get_or_create_billing_account(
        _SYSTEM,
        payer_tenant_id,
        merchant_tenant_id=merchant_tenant_id,
        merchant_account_id=merchant_account_id,
    )
    return view.id


def _client_only_member(agency_owner_id: uuid.UUID, client_tenant_id: uuid.UUID):
    """Mirrors `tests/billing/test_commercial_subscriptions_integration.py
    ::_client_only_member()` -- a user whose only role anywhere is
    `member` at the client."""
    member = make_user()
    sent = invite_client_member(agency_owner_id, client_tenant_id, f"{_name('member')}@example.com")
    accept_client_invitation(sent.raw_token, member.id, client_tenant_id)
    return member


# --- BillingAccount representation ------------------------------------------


def test_payer_can_list_its_own_billing_accounts_over_http() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/billing-accounts",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        row = body[0]
        assert row["id"] == str(account_id)
        assert row["tenant_id"] == str(agency.tenant_id)
        assert row["merchant_tenant_id"] == str(agency.tenant_id)
        assert row["merchant_account_id"] == str(merchant.id)
        assert row["status"] == "active"
        assert "provider" not in row  # no provider/secret leakage
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_unauthenticated_billing_accounts_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.get(f"/v1/billing/tenants/{uuid.uuid4()}/billing-accounts")
    assert response.status_code == 401


def test_unrelated_tenant_cannot_list_another_tenants_billing_accounts_over_http() -> None:
    """Attack 3 (BillingAccount substitution), read side: a stranger with
    no role at `agency.tenant_id` at all cannot list its billing
    accounts just by naming its id in the path."""
    owner = make_user()
    stranger = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/billing-accounts",
            headers=_auth_headers(stranger.id),
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


# --- Commercial subscriptions: wiring, through to the provider boundary ----
#
# No test in this section can assert an actual `201` (a genuinely created
# subscription): `create_commercial_subscription_route()` deliberately
# accepts no `provider` override (module docstring of `product/billing
# /routes.py`, "a caller cannot choose their own payment provider" --
# the identical, pre-existing rule the legacy `/subscriptions` route
# already has, see *that* module's own docstring, "Subscription/plan
# -change/cancel routes are deliberately NOT exercised here"). Without an
# override, `core.billing.commercial._adapter_for_merchant()` resolves a
# real `StripeBillingProvider` only for a merchant owned by the platform
# tenant -- and even that needs a `STRIPE_API_KEY` this repository's own
# `.env.example` never configures (confirmed directly, same finding
# `product/billing/parties.py`'s own module docstring already made for
# Step 2). For every other merchant (every one of these tests' own
# `provider="fake"` test double included), it raises
# `BillingProviderMismatchError` -- mapped to this router's own `503`.
# This is a genuine, pre-existing, cross-cutting environment constraint,
# not something Step 5 introduces or could close (no Stripe Connect, no
# real Stripe key -- both explicitly out of this phase's own scope).
#
# What these tests prove instead: a well-formed, fully-authorized
# request -- self-pay or sponsored alike -- reaches exactly that
# provider boundary, never an earlier 400/401/404 the request's own
# shape should not deserve. Actual creation success, idempotent replay,
# and entitlement/payer correctness are already exhaustively proven at
# the service layer, against the identical, unchanged
# `create_commercial_subscription()` this route calls --
# `tests/billing/test_commercial_subscriptions_integration.py` (23 tests)
# and `tests/billing/test_catalog_integration.py` (15 tests), both of
# which supply an explicit `FakeBillingProvider()` directly to the
# Python function -- a legitimate thing for a direct function call to do,
# never exposed as a caller-controlled HTTP parameter.


def test_self_pay_commercial_subscription_reaches_the_provider_boundary_over_http() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    plan = create_owned_plan(
        owner.id,
        agency.tenant_id,
        merchant_account_id=merchant.id,
        key=_name("plan"),
        name="Self-pay",
        entitlements={"max_users": 3},
        visibility=PlanVisibility.PUBLIC,
    )
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{agency.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner.id),
            json={
                "payer_tenant_id": str(agency.tenant_id),
                "billing_account_id": str(account_id),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        # 503, never 400/401/403/404: authorization (payer charge +
        # service create), billing-account resolution, and plan
        # eligibility all passed for this self-pay shape (section
        # comment above).
        assert response.status_code == 503, response.text
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_sponsored_commercial_subscription_reaches_the_provider_boundary_over_http() -> None:
    """The identical proof as self-pay above, for `payer_tenant_id !=
    service_tenant_id` -- sponsorship is not somehow more restricted (or
    less) than self-pay at the wiring/authorization layer; both reach the
    same boundary."""
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    plan = create_owned_plan(
        owner.id,
        agency.tenant_id,
        merchant_account_id=merchant.id,
        key=_name("plan"),
        name="Resold",
        entitlements={"max_users": 7},
        visibility=PlanVisibility.UNLISTED,
    )
    create_plan_offer(owner.id, agency.tenant_id, plan.id, service_tenant_id=client.tenant_id)
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{client.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner.id),
            json={
                "payer_tenant_id": str(agency.tenant_id),
                "billing_account_id": str(account_id),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 503, response.text
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Commercial subscriptions: retrieval (no provider involved) ------------
#
# Reading back an existing commercial subscription touches no payment
# provider at all -- created here at the service layer (an explicit
# `FakeBillingProvider()`, a legitimate direct function argument, module
# comment above), then read back over real HTTP, end to end.


def test_get_commercial_subscription_over_http() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    plan = create_owned_plan(
        owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=_name("plan"), name="Pro"
    )
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    created = create_commercial_subscription(
        owner.id,
        payer_tenant_id=agency.tenant_id,
        service_tenant_id=agency.tenant_id,
        billing_account_id=account_id,
        plan_id=plan.id,
        idempotency_key=_name("idem"),
        provider=FakeBillingProvider(),
    )
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/commercial-subscriptions/{created.id}",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(created.id)
        assert body["payer_tenant_id"] == str(agency.tenant_id)
        assert body["service_tenant_id"] == str(agency.tenant_id)
        assert body["billing_account_id"] == str(account_id)
        assert body["plan_id"] == str(plan.id)
        assert body["status"] == "active"
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_tenant_cannot_retrieve_another_tenants_commercial_subscription_over_http() -> (
    None
):
    owner = make_user()
    stranger = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    plan = create_owned_plan(
        owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=_name("plan"), name="Pro"
    )
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    created = create_commercial_subscription(
        owner.id,
        payer_tenant_id=agency.tenant_id,
        service_tenant_id=agency.tenant_id,
        billing_account_id=account_id,
        plan_id=plan.id,
        idempotency_key=_name("idem"),
        provider=FakeBillingProvider(),
    )
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/commercial-subscriptions/{created.id}",
            headers=_auth_headers(stranger.id),
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


# --- Security: the six named attacks (Step 5 task, section 15) -------------


def test_attack_1_payer_substitution_is_denied() -> None:
    """Authorized for service tenant (its own client), attacker supplies
    an unrelated payer tenant it has no reach into at all."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, _m_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    client_a = provision_client(owner_a.id, agency_a.tenant_id, _name("client-a"))
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    plan = create_owned_plan(
        owner_b.id,
        agency_b.tenant_id,
        merchant_account_id=merchant_b.id,
        key=_name("plan"),
        name="X",
    )
    account_b = _billing_account_id(
        agency_b.tenant_id, merchant_tenant_id=agency_b.tenant_id, merchant_account_id=merchant_b.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{client_a.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner_a.id),
            json={
                "payer_tenant_id": str(agency_b.tenant_id),
                "billing_account_id": str(account_b),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_attack_2_service_substitution_is_denied() -> None:
    """Authorized for the payer (its own agency), attacker supplies an
    unrelated service tenant it has no reach into at all."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, _m_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    plan = create_owned_plan(
        owner_a.id,
        agency_a.tenant_id,
        merchant_account_id=merchant_a.id,
        key=_name("plan"),
        name="X",
    )
    account_a = _billing_account_id(
        agency_a.tenant_id, merchant_tenant_id=agency_a.tenant_id, merchant_account_id=merchant_a.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{agency_b.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner_a.id),
            json={
                "payer_tenant_id": str(agency_a.tenant_id),
                "billing_account_id": str(account_a),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_attack_3_billing_account_substitution_is_denied() -> None:
    """Authorized for both its own payer and service tenant (self-pay),
    attacker supplies another tenant's own `billing_account_id`."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    plan = create_owned_plan(
        owner_a.id,
        agency_a.tenant_id,
        merchant_account_id=merchant_a.id,
        key=_name("plan"),
        name="X",
    )
    account_b = _billing_account_id(
        agency_b.tenant_id, merchant_tenant_id=agency_b.tenant_id, merchant_account_id=merchant_b.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{agency_a.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner_a.id),
            json={
                "payer_tenant_id": str(agency_a.tenant_id),
                "billing_account_id": str(account_b),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_attack_4_catalog_enumeration_is_denied() -> None:
    """Covered end-to-end in `tests/billing/test_routes_integration.py
    ::test_unrelated_actor_cannot_list_an_unrelated_tenants_catalog_over_http`
    -- repeated here, against a plan with a real `active` merchant (so
    the plan is genuinely eligible for *someone*), to prove the denial is
    about authorization, not merely about there being nothing to see."""
    owner = make_user()
    stranger = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    create_owned_plan(
        owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=_name("plan"), name="X"
    )
    try:
        api = TestClient(create_app())
        response = api.get(
            f"/v1/billing/tenants/{agency.tenant_id}/plans", headers=_auth_headers(stranger.id)
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_attack_5_hierarchy_abuse_is_denied() -> None:
    """A descendant (a client-only actor) attempts to cause its parent
    agency to pay merely because the agency's own `SUBTREE` role reaches
    the client -- that reach is directional (parent -> descendant) and
    never the reverse; the client has no role *at* the agency at all."""
    agency_owner = make_user()
    agency, merchant = _agency_with_active_merchant(agency_owner.id)
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    plan = create_owned_plan(
        agency_owner.id,
        agency.tenant_id,
        merchant_account_id=merchant.id,
        key=_name("plan"),
        name="X",
    )
    account_id = _billing_account_id(
        agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{client.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(client_member.id),
            json={
                "payer_tenant_id": str(agency.tenant_id),
                "billing_account_id": str(account_id),
                "plan_id": str(plan.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


def test_attack_6_plan_ownership_substitution_is_denied() -> None:
    """Caller is fully authorized for both payer and service tenant
    (self-pay), but supplies a plan owned by an unrelated tenant it has
    no catalog reach into -- denied via the frozen contract's own
    non-enumerating `PlanNotEligibleError`, mapped to the identical `404`
    every other denial in this router already uses."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    plan_b = create_owned_plan(
        owner_b.id,
        agency_b.tenant_id,
        merchant_account_id=merchant_b.id,
        key=_name("plan"),
        name="B's Plan",
        visibility=PlanVisibility.PRIVATE,
    )
    account_a = _billing_account_id(
        agency_a.tenant_id, merchant_tenant_id=agency_a.tenant_id, merchant_account_id=merchant_a.id
    )
    try:
        api = TestClient(create_app())
        response = api.post(
            f"/v1/billing/tenants/{agency_a.tenant_id}/commercial-subscriptions",
            headers=_auth_headers(owner_a.id),
            json={
                "payer_tenant_id": str(agency_a.tenant_id),
                "billing_account_id": str(account_a),
                "plan_id": str(plan_b.id),
                "idempotency_key": _name("idem"),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_unauthenticated_commercial_subscription_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.post(
        f"/v1/billing/tenants/{uuid.uuid4()}/commercial-subscriptions",
        json={
            "payer_tenant_id": str(uuid.uuid4()),
            "billing_account_id": str(uuid.uuid4()),
            "plan_id": str(uuid.uuid4()),
            "idempotency_key": _name("idem"),
        },
    )
    assert response.status_code == 401
