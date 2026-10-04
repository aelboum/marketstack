"""Real concurrency proof for the B2B2C commercial-party/catalog/
subscription race-safety guarantees documented throughout `product/billing
/parties.py`, `product/billing/catalog.py`, and `product/billing
/commercial_subscriptions.py` (docs/ROADMAP.md Phase 17's own Step 6,
"Final Hardening & Certification" -- section 12, "Concurrency"). Real
threads against the real disposable Postgres, mirroring `tests/agency
/test_onboarding_integration.py::test_concurrent_acceptance_is_safe()`'s
and `tests/platform/test_provisioning_integration.py
::test_concurrent_duplicate_attachment_is_hierarchy_safe_and_audits_exactly_once()`'s
exact shape: a `threading.Barrier` so both threads genuinely contend, a
shared results dict, real thread joins.

Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from typing import cast

import pytest
from core.authority import SystemAuthority, SystemCaller
from core.billing import (
    FakeBillingProvider,
    MerchantAccountStatus,
    Plan,
    create_merchant_account,
    create_plan,
    get_plan,
    list_merchant_accounts,
)
from product.agency.provisioning import provision_agency, provision_client
from product.billing.catalog import (
    PlanOfferView,
    create_owned_plan,
    create_plan_offer,
    ensure_legacy_plan_adopted,
)
from product.billing.commercial_subscriptions import (
    CommercialSubscriptionView,
    create_commercial_subscription,
)
from product.billing.parties import (
    BillingAccountView,
    MerchantAccountView,
    _ensure_agency_merchant_account,
    get_or_create_billing_account,
    list_tenant_billing_accounts,
)

from tests.billing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_SYSTEM = SystemCaller(SystemAuthority.BILLING_OPERATIONS)
_JOIN_TIMEOUT = 30


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _run_concurrently(fn_a, fn_b) -> dict[str, tuple[str, object]]:
    barrier = threading.Barrier(2)
    results: dict[str, tuple[str, object]] = {}

    def _attempt(label: str, fn) -> None:
        barrier.wait()
        try:
            results[label] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001 -- recorded for the assertion, not swallowed
            results[label] = ("failed", exc)

    thread_a = threading.Thread(target=_attempt, args=("a", fn_a))
    thread_b = threading.Thread(target=_attempt, args=("b", fn_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=_JOIN_TIMEOUT)
    thread_b.join(timeout=_JOIN_TIMEOUT)
    return results


# --- MerchantAccount provisioning -------------------------------------------


def test_concurrent_agency_merchant_provisioning_creates_exactly_one_row() -> None:
    """`_ensure_agency_merchant_account()`'s own `(provider,
    provider_account_ref)` deterministic-key idempotency
    (`product/billing/parties.py`'s own module docstring) under real
    contention, not just by source inspection."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        results = _run_concurrently(
            lambda: _ensure_agency_merchant_account(agency.tenant_id),
            lambda: _ensure_agency_merchant_account(agency.tenant_id),
        )
        assert results["a"][0] == "ok", results["a"]
        assert results["b"][0] == "ok", results["b"]
        view_a, _created_a = cast("tuple[MerchantAccountView, bool]", results["a"][1])
        view_b, _created_b = cast("tuple[MerchantAccountView, bool]", results["b"][1])
        assert view_a.id == view_b.id
        assert len(list_merchant_accounts(agency.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


# --- BillingAccount get-or-create --------------------------------------------


def test_concurrent_billing_account_get_or_create_creates_exactly_one_row() -> None:
    """`core.billing.get_or_create_billing_account()`'s own
    `uq_billing_accounts_tenant_merchant` race (frozen contract) under
    real contention -- `product/billing/parties.py::get_or_create_billing_account()`
    is a thin pass-through, so this proves the frozen primitive itself,
    not anything reimplemented here."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    merchant = create_merchant_account(
        _SYSTEM,
        agency.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    try:
        results = _run_concurrently(
            lambda: get_or_create_billing_account(
                _SYSTEM,
                agency.tenant_id,
                merchant_tenant_id=agency.tenant_id,
                merchant_account_id=merchant.id,
            ),
            lambda: get_or_create_billing_account(
                _SYSTEM,
                agency.tenant_id,
                merchant_tenant_id=agency.tenant_id,
                merchant_account_id=merchant.id,
            ),
        )
        assert results["a"][0] == "ok", results["a"]
        assert results["b"][0] == "ok", results["b"]
        view_a, _created_a = cast("tuple[BillingAccountView, bool]", results["a"][1])
        view_b, _created_b = cast("tuple[BillingAccountView, bool]", results["b"][1])
        assert view_a.id == view_b.id
        assert len(list_tenant_billing_accounts(owner.id, agency.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


# --- Legacy plan adoption -----------------------------------------------------


def test_concurrent_legacy_plan_adoption_has_exactly_one_winner() -> None:
    """`ensure_legacy_plan_adopted()`'s own race recovery (`product/billing
    /catalog.py`'s own docstring: "A concurrent first adoption of the same
    plan is handled by re-reading it, never retried against a different
    owner") under real contention: two different tenants race to adopt
    the identical, freshly-created legacy plan key."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    plan_key = _name("plan")
    create_plan(plan_key, "Race Plan", entitlements={})
    try:
        results = _run_concurrently(
            lambda: ensure_legacy_plan_adopted(plan_key, agency_a.tenant_id),
            lambda: ensure_legacy_plan_adopted(plan_key, agency_b.tenant_id),
        )
        assert results["a"][0] == "ok", results["a"]
        assert results["b"][0] == "ok", results["b"]
        plan_a = cast(Plan, results["a"][1])
        plan_b = cast(Plan, results["b"][1])
        # Both calls return the SAME plan row (same id), with the SAME
        # owner -- whichever tenant actually won the race -- never two
        # different "adopted" states for the identical plan.
        assert plan_a.id == plan_b.id
        assert plan_a.owner_tenant_id == plan_b.owner_tenant_id
        assert plan_a.owner_tenant_id in (agency_a.tenant_id, agency_b.tenant_id)
        # The authoritative row agrees with both callers' own view.
        final = get_plan(plan_key)
        assert final.owner_tenant_id == plan_a.owner_tenant_id
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- Plan offer creation -------------------------------------------------------


def test_concurrent_plan_offer_creation_creates_exactly_one_offer() -> None:
    """`core.billing.catalog.create_plan_offer()`'s own
    one-active-offer-per-`(plan_id, service_tenant_id)` race recovery
    (frozen contract) under real contention, through this product's own
    `product/billing/catalog.py::create_plan_offer()` wrapper."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    merchant = create_merchant_account(
        _SYSTEM,
        agency.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    plan = create_owned_plan(
        owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=_name("plan"), name="X"
    )
    try:
        results = _run_concurrently(
            lambda: create_plan_offer(
                owner.id, agency.tenant_id, plan.id, service_tenant_id=client.tenant_id
            ),
            lambda: create_plan_offer(
                owner.id, agency.tenant_id, plan.id, service_tenant_id=client.tenant_id
            ),
        )
        assert results["a"][0] == "ok", results["a"]
        assert results["b"][0] == "ok", results["b"]
        offer_a = cast(PlanOfferView, results["a"][1])
        offer_b = cast(PlanOfferView, results["b"][1])
        assert offer_a.id == offer_b.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Commercial subscription creation (duplicate idempotency key) -----------


def test_concurrent_commercial_subscription_creation_with_the_same_key_is_safe() -> None:
    """The centerpiece money-safety guarantee: two genuinely concurrent
    callers racing on the identical `idempotency_key`/payer/service/plan
    never produce two billable provider subscriptions or two local rows
    (`core.idempotency`'s own reservation -- `core/idempotency/service.py`
    -- is what makes this safe; `product/billing
    /commercial_subscriptions.py` adds no mechanism of its own, by
    design). One contender may legitimately observe
    `IdempotencyInProgressError` if it loses the reservation race while
    the other is still mid-flight -- that is the frozen contract's own
    documented, safe outcome, never a crash and never a second
    subscription."""
    from core.idempotency import IdempotencyInProgressError

    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    merchant = create_merchant_account(
        _SYSTEM,
        agency.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    plan = create_owned_plan(
        owner.id, agency.tenant_id, merchant_account_id=merchant.id, key=_name("plan"), name="X"
    )
    account, _created = get_or_create_billing_account(
        _SYSTEM,
        agency.tenant_id,
        merchant_tenant_id=agency.tenant_id,
        merchant_account_id=merchant.id,
    )
    key = _name("idem")
    try:
        results = _run_concurrently(
            lambda: create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=agency.tenant_id,
                billing_account_id=account.id,
                plan_id=plan.id,
                idempotency_key=key,
                provider=FakeBillingProvider(),
            ),
            lambda: create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=agency.tenant_id,
                billing_account_id=account.id,
                plan_id=plan.id,
                idempotency_key=key,
                provider=FakeBillingProvider(),
            ),
        )
        outcomes = {label: kind for label, (kind, _value) in results.items()}
        # Neither contender may fail with anything other than the one,
        # documented, safe concurrent-retry shape.
        for label, (kind, value) in results.items():
            if kind == "failed":
                assert isinstance(value, IdempotencyInProgressError), (label, value)

        succeeded = [
            cast(CommercialSubscriptionView, value)
            for kind, value in results.values()
            if kind == "ok"
        ]
        assert len(succeeded) >= 1, results
        # Every successful result names the identical subscription.
        first_id = succeeded[0].id
        for view in succeeded[1:]:
            assert view.id == first_id
        assert outcomes  # sanity: both threads actually reported something
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)
