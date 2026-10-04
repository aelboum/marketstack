"""`product/billing/catalog.py`: the Catalog v2 owned-plan/plan-offer
wrapper over the frozen SaaS-OS `core.billing.catalog` contract
(docs/ROADMAP.md Phase 16, Step 4). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.

Covers: owned-plan creation/retrieval/duplicate-key handling, plan-offer
creation/retrieval/idempotency, plan isolation (ownership never leaks to
an unrelated tenant, a client, or a service/payer tenant), and
integration with Step 3's sponsored-subscription path -- self-pay and
sponsored subscriptions against a real owned plan/offer, invalid-plan and
missing-offer refusals, and the ownership invariants section 6/11 of the
Step 4 task require: plan/merchant ownership never silently moves to the
service tenant or the payer.

Does NOT use Step 2's own `"stripe"`-provider commercial-party merchants
(`product/billing/parties.py::_ensure_agency_merchant_account()`, which
stays `onboarding` forever absent real Stripe Connect) -- every merchant
here is a dedicated, test-only `provider="fake"` `MerchantAccount`
created `active` directly, exactly `tests/billing
/test_commercial_subscriptions_integration.py`'s own fixture pattern,
needed because `evaluate_plan_eligibility()` requires an `active`
merchant and no real Stripe account is configured in this environment.
"""

from __future__ import annotations

import uuid

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.billing import (
    FakeBillingProvider,
    MerchantAccountStatus,
    PlanVisibility,
    create_merchant_account,
    list_plans,
)
from core.billing.errors import DuplicateOwnedPlanKeyError, PlanNotEligibleError
from product.agency.onboarding import accept_client_invitation, invite_client_member
from product.agency.provisioning import provision_agency, provision_client
from product.billing.catalog import (
    create_owned_plan,
    create_plan_offer,
    get_owned_plan,
    set_plan_visibility,
)
from product.billing.commercial_subscriptions import create_commercial_subscription
from product.billing.errors import BillingAccessDeniedError
from product.billing.parties import get_or_create_billing_account

from tests.billing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_SYSTEM = SystemCaller(SystemAuthority.BILLING_OPERATIONS)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_with_active_merchant(owner_id: uuid.UUID, prefix: str = "agency"):
    """A real agency plus a dedicated, test-only `provider="fake"`
    `MerchantAccount`, created `active` -- module docstring."""
    agency = provision_agency(owner_id, _name(prefix))
    merchant = create_merchant_account(
        _SYSTEM,
        agency.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    return agency, merchant


def _client_only_member(agency_owner_id: uuid.UUID, client_tenant_id: uuid.UUID):
    """A user whose *only* role anywhere is `member` at `client_tenant_id`
    -- mirrors `tests/billing/test_commercial_subscriptions_integration.py
    ::_client_only_member()`'s own identical rationale: `provision_client()`
    performs no first-role bootstrap at the client at all, so the real
    invite -> accept chain is the only way to get a user scoped to just
    the client."""
    member = make_user()
    sent = invite_client_member(agency_owner_id, client_tenant_id, f"{_name('member')}@example.com")
    accept_client_invitation(sent.raw_token, member.id, client_tenant_id)
    return member


def _billing_account_id(
    payer_tenant_id: uuid.UUID, *, merchant_tenant_id: uuid.UUID, merchant_account_id: uuid.UUID
) -> uuid.UUID:
    view, _created = get_or_create_billing_account(
        _SYSTEM,
        payer_tenant_id,
        merchant_tenant_id=merchant_tenant_id,
        merchant_account_id=merchant_account_id,
    )
    return view.id


# --- Owned plan creation / retrieval ----------------------------------------


def test_owner_can_create_and_retrieve_an_owned_plan() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    try:
        plan = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Pro",
            entitlements={"max_users": 10},
            visibility=PlanVisibility.PUBLIC,
        )
        assert plan.owner_tenant_id == agency.tenant_id
        assert plan.merchant_account_id == merchant.id
        assert plan.status == "active"

        fetched = get_owned_plan(owner.id, agency.tenant_id, plan.id)
        assert fetched is not None
        assert fetched.id == plan.id
        assert fetched.entitlements == {"max_users": 10}
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_key_for_same_owner_raises() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    try:
        key = _name("plan")
        create_owned_plan(
            owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=key, name="Pro"
        )
        with pytest.raises(DuplicateOwnedPlanKeyError):
            create_owned_plan(
                owner.id,
                agency.tenant_id,
                merchant_account_id=merchant.id,
                key=key,
                name="Pro Again",
            )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_two_owners_may_independently_use_the_identical_key() -> None:
    """Owned-plan keys are unique per owner, never globally (`core/billing
    /catalog.py`'s own module docstring: "two owners may share a key") --
    proves this product's own wrapper does not add a global constraint
    the frozen contract does not have."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    try:
        key = _name("shared-key")
        plan_a = create_owned_plan(
            owner_a.id, agency_a.tenant_id, merchant_account_id=merchant_a.id, key=key, name="A"
        )
        plan_b = create_owned_plan(
            owner_b.id, agency_b.tenant_id, merchant_account_id=merchant_b.id, key=key, name="B"
        )
        assert plan_a.id != plan_b.id
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- Plan isolation (Step 4 task, section 12) -------------------------------


def test_agency_a_cannot_modify_agency_bs_owned_plan() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    try:
        plan_b = create_owned_plan(
            owner_b.id,
            agency_b.tenant_id,
            merchant_account_id=merchant_b.id,
            key=_name("plan"),
            name="B's Plan",
        )
        with pytest.raises(BillingAccessDeniedError):
            set_plan_visibility(owner_a.id, agency_b.tenant_id, plan_b.id, PlanVisibility.PRIVATE)
        # Unchanged.
        still = get_owned_plan(owner_b.id, agency_b.tenant_id, plan_b.id)
        assert still is not None
        assert still.visibility == "public"
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_a_cannot_create_an_offer_against_agency_bs_plan() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, _merchant_a = _agency_with_active_merchant(owner_a.id, "agency-a")
    agency_b, merchant_b = _agency_with_active_merchant(owner_b.id, "agency-b")
    client_a = provision_client(owner_a.id, agency_a.tenant_id, _name("client-a"))
    try:
        plan_b = create_owned_plan(
            owner_b.id,
            agency_b.tenant_id,
            merchant_account_id=merchant_b.id,
            key=_name("plan"),
            name="B's Plan",
            visibility=PlanVisibility.UNLISTED,
        )
        with pytest.raises(BillingAccessDeniedError):
            create_plan_offer(
                owner_a.id,
                agency_b.tenant_id,
                plan_b.id,
                service_tenant_id=client_a.tenant_id,
            )
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_cannot_modify_its_parent_agencys_owned_plan() -> None:
    """A client's own member (its only role is at the client, downward
    `SUBTREE` never reaches upward) cannot manage its parent agency's
    catalog -- explicit authorization, never inferred from hierarchy."""
    agency_owner = make_user()
    agency, merchant = _agency_with_active_merchant(agency_owner.id)
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    try:
        plan = create_owned_plan(
            agency_owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Pro",
        )
        with pytest.raises(BillingAccessDeniedError):
            set_plan_visibility(client_member.id, agency.tenant_id, plan.id, PlanVisibility.PRIVATE)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


def test_unrelated_tenant_cannot_access_another_tenants_private_catalog() -> None:
    owner_a = make_user()
    stranger = make_user()
    agency_a, merchant_a = _agency_with_active_merchant(owner_a.id)
    try:
        plan = create_owned_plan(
            owner_a.id,
            agency_a.tenant_id,
            merchant_account_id=merchant_a.id,
            key=_name("plan"),
            name="Private Plan",
            visibility=PlanVisibility.PRIVATE,
        )
        # The owner itself can always see its own plan.
        assert get_owned_plan(owner_a.id, agency_a.tenant_id, plan.id) is not None
        # A stranger with no role at agency_a at all cannot -- non-
        # enumerating: "not found," never "found but private."
        assert get_owned_plan(stranger.id, agency_a.tenant_id, plan.id) is None
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_users(owner_a.id, stranger.id)


def test_service_tenant_cannot_silently_become_plan_owner() -> None:
    """A client, as the eligible service tenant for its agency's own
    `descendants`-visibility plan, can see that plan -- but the
    `owner_tenant_id` field in what it sees is unconditionally still the
    agency's; nothing about being the eligible service tenant ever
    rewrites, or lets a client rewrite, that ownership."""
    agency_owner = make_user()
    agency, merchant = _agency_with_active_merchant(agency_owner.id)
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    try:
        plan = create_owned_plan(
            agency_owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Pro",
            visibility=PlanVisibility.DESCENDANTS,
        )
        # get_owned_plan() always scopes service_tenant_id=owner_tenant_id
        # (its own docstring) -- a client-only actor cannot use it at all
        # to look up the agency's own catalog by that name (no role
        # there), proving isolation independently of the eligibility scan
        # below.
        assert get_owned_plan(client_member.id, agency.tenant_id, plan.id) is None

        seen_by_client = next(
            p
            for p in list_plans(UserCaller(client_member.id), service_tenant_id=client.tenant_id)
            if p.id == plan.id
        )
        assert seen_by_client.owner_tenant_id == agency.tenant_id
        assert seen_by_client.owner_tenant_id != client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


# --- Plan offers -------------------------------------------------------------


def test_create_plan_offer_for_unlisted_plan_makes_it_eligible_for_only_that_tenant() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    client_a = provision_client(owner.id, agency.tenant_id, _name("client-a"))
    client_b = provision_client(owner.id, agency.tenant_id, _name("client-b"))
    try:
        plan = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Unlisted",
            visibility=PlanVisibility.UNLISTED,
        )
        offer = create_plan_offer(
            owner.id, agency.tenant_id, plan.id, service_tenant_id=client_a.tenant_id
        )
        assert offer.plan_id == plan.id
        assert offer.service_tenant_id == client_a.tenant_id
        assert offer.owner_tenant_id == agency.tenant_id
        assert offer.status == "active"

        account_a = _billing_account_id(
            agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
        )
        # client_a: offered -- eligible, subscription succeeds.
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency.tenant_id,
            service_tenant_id=client_a.tenant_id,
            billing_account_id=account_a,
            plan_id=plan.id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.service_tenant_id == client_a.tenant_id

        # client_b: never offered -- ineligible, PlanNotEligibleError.
        with pytest.raises(PlanNotEligibleError) as excinfo:
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=client_b.tenant_id,
                billing_account_id=account_a,
                plan_id=plan.id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.reason == "no_offer"
    finally:
        cleanup_tenant_tree(client_a.tenant_id, client_b.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_repeated_plan_offer_creation_is_idempotent() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        plan = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Unlisted",
            visibility=PlanVisibility.UNLISTED,
        )
        first = create_plan_offer(
            owner.id, agency.tenant_id, plan.id, service_tenant_id=client.tenant_id
        )
        second = create_plan_offer(
            owner.id, agency.tenant_id, plan.id, service_tenant_id=client.tenant_id
        )
        assert second.id == first.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_offer_for_a_different_plan_does_not_grant_eligibility() -> None:
    """An offer is scoped to exactly one `(plan_id, service_tenant_id)`
    pair -- offering plan A to a client never makes plan B eligible for
    that same client, even though both are the identical owner's own
    unlisted plans."""
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        plan_a = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan-a"),
            name="A",
            visibility=PlanVisibility.UNLISTED,
        )
        plan_b = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan-b"),
            name="B",
            visibility=PlanVisibility.UNLISTED,
        )
        create_plan_offer(owner.id, agency.tenant_id, plan_a.id, service_tenant_id=client.tenant_id)

        account_id = _billing_account_id(
            agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
        )
        with pytest.raises(PlanNotEligibleError) as excinfo:
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=client.tenant_id,
                billing_account_id=account_id,
                plan_id=plan_b.id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.reason == "no_offer"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Subscription integration with Step 3 (Step 4 task, section 11) --------


def test_self_pay_subscription_against_an_owned_plan() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    try:
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
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency.tenant_id,
            service_tenant_id=agency.tenant_id,
            billing_account_id=account_id,
            plan_id=plan.id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.payer_tenant_id == agency.tenant_id
        assert view.service_tenant_id == agency.tenant_id
        assert view.plan_id == plan.id
        assert view.status == "active"
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_sponsored_subscription_against_an_agency_owned_plan_via_offer() -> None:
    """The exact ownership model Step 4's own task (section 6) names for
    an agency-owned commercial plan: plan owner = agency, offer owner =
    agency, merchant owner = agency, payer = agency, service tenant =
    client, entitlement recipient = client. Reuses Step 3's own dual
    authorization unchanged (`product/billing/commercial_subscriptions.py`)."""
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
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
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency.tenant_id,
            service_tenant_id=client.tenant_id,
            billing_account_id=account_id,
            plan_id=plan.id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.payer_tenant_id == agency.tenant_id
        assert view.merchant_account_id == merchant.id
        assert view.service_tenant_id == client.tenant_id
        assert view.plan_id == plan.id
        assert view.status == "active"

        # Payer ownership (section 12, point 7) never becomes plan
        # ownership: the plan is still the agency's own, not the client's
        # -- confirmed from the client's own eligibility-scoped view
        # (get_owned_plan() cannot be used here: it always scopes
        # service_tenant_id=owner_tenant_id, and this plan is `unlisted`
        # with no offer to the agency itself).
        seen = next(
            p
            for p in list_plans(UserCaller(owner.id), service_tenant_id=client.tenant_id)
            if p.id == plan.id
        )
        assert seen.owner_tenant_id == agency.tenant_id
        assert seen.owner_tenant_id != client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_plan_id_raises_plan_not_eligible() -> None:
    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    try:
        account_id = _billing_account_id(
            agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
        )
        with pytest.raises(PlanNotEligibleError) as excinfo:
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=agency.tenant_id,
                billing_account_id=account_id,
                plan_id=uuid.uuid4(),
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.reason == "not_found"
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_withdrawn_plan_cannot_be_subscribed_to() -> None:
    """Lifecycle/status (Step 4 task, section 13): `withdraw_plan()`
    (used directly here, via `core.billing` -- this module does not wrap
    it, since no test above needs to) stops new subscriptions only."""
    from core.authority import UserCaller
    from core.billing import withdraw_plan

    owner = make_user()
    agency, merchant = _agency_with_active_merchant(owner.id)
    try:
        plan = create_owned_plan(
            owner.id,
            agency.tenant_id,
            merchant_account_id=merchant.id,
            key=_name("plan"),
            name="Pro",
        )
        withdraw_plan(UserCaller(owner.id), agency.tenant_id, plan.id)
        account_id = _billing_account_id(
            agency.tenant_id, merchant_tenant_id=agency.tenant_id, merchant_account_id=merchant.id
        )
        with pytest.raises(PlanNotEligibleError) as excinfo:
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=agency.tenant_id,
                billing_account_id=account_id,
                plan_id=plan.id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.reason == "withdrawn"
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)
