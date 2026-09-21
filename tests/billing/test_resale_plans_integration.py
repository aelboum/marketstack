"""`product/billing/resale_plans.py`: resale-plan CRUD, the resale-tier
ceiling check, tenant isolation, authorization, and tenant-lifecycle
denial (docs/ROADMAP.md Phase 13.2). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.billing import create_plan, subscribe
from core.billing.provider import FakeBillingProvider
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.billing.errors import (
    BillingAccessDeniedError,
    BillingConflictError,
    BillingReferenceNotFoundError,
    BillingValidationError,
    ResaleTierCeilingExceededError,
)
from product.billing.pagination import MAX_PAGE_SIZE
from product.billing.resale_plans import (
    create_resale_plan,
    deactivate_resale_plan,
    get_resale_plan,
    list_resale_plans,
    update_resale_plan,
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


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _give_agency_a_platform_subscription(owner_id, agency_tenant_id, entitlements: dict) -> str:
    """Subscribes `agency_tenant_id` to a fresh, throwaway platform plan
    carrying `entitlements` -- the reseller's own ceiling for the resale-
    tier ceiling check. Returns the plan key (for cleanup)."""
    plan_key = _name("platform-plan")
    create_plan(plan_key, "Throwaway Platform Plan", entitlements=entitlements)
    subscribe(agency_tenant_id, plan_key, provider=FakeBillingProvider(), actor_user_id=owner_id)
    return plan_key


# --- Valid creation --------------------------------------------------------------


def test_create_resale_plan_valid() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 50, "advanced_reports": True}
    )
    plan_keys = [platform_key]
    try:
        plan = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="starter",
            name="Starter",
            price_amount=1999,
            price_currency="usd",
            entitlements={"max_users": 5},
        )
        plan_keys.append(plan.underlying_plan_key)
        assert plan.tenant_id == agency.tenant_id
        assert plan.price_currency == "USD"
        assert plan.status == "enabled"
        assert plan.underlying_plan_key.startswith("resale:")

        fetched = get_resale_plan(owner.id, agency.tenant_id, plan.id)
        assert fetched.id == plan.id

        listed = list_resale_plans(owner.id, agency.tenant_id)
        assert any(p.id == plan.id for p in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


# --- Resale-tier ceiling check ----------------------------------------------------


def test_create_resale_plan_rejects_numeric_entitlement_exceeding_ceiling() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    try:
        with pytest.raises(ResaleTierCeilingExceededError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="too-big",
                name="Too Big",
                price_amount=0,
                price_currency="USD",
                entitlements={"max_users": 10},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key)


def test_create_resale_plan_rejects_boolean_entitlement_the_reseller_lacks() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"advanced_reports": False}
    )
    try:
        with pytest.raises(ResaleTierCeilingExceededError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="fancy",
                name="Fancy",
                price_amount=0,
                price_currency="USD",
                entitlements={"advanced_reports": True},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key)


def test_create_resale_plan_rejects_entitlement_key_absent_from_ceiling() -> None:
    """A reseller with NO active subscription has an empty entitlements
    ceiling (`core.billing.get_entitlements()`'s own "no active
    subscription -> {}" default) -- any truthy/positive resale value is
    rejected."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ResaleTierCeilingExceededError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="nope",
                name="Nope",
                price_amount=0,
                price_currency="USD",
                entitlements={"max_users": 1},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_resale_plan_allows_entitlement_within_ceiling() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 100, "advanced_reports": True}
    )
    resale_plan_key = None
    try:
        plan = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="within",
            name="Within Ceiling",
            price_amount=500,
            price_currency="EUR",
            entitlements={"max_users": 10, "advanced_reports": True},
        )
        resale_plan_key = plan.underlying_plan_key
        assert plan.entitlements == {"max_users": 10, "advanced_reports": True}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        keys = [platform_key] + ([resale_plan_key] if resale_plan_key else [])
        cleanup_global_plan_keys(*keys)


def test_create_resale_plan_rejects_unsupported_entitlement_value_type() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    try:
        with pytest.raises(BillingValidationError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="badtype",
                name="Bad Type",
                price_amount=0,
                price_currency="USD",
                entitlements={"max_users": "unlimited"},
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key)


# --- Invalid input ------------------------------------------------------------


def test_create_resale_plan_rejects_duplicate_key_within_same_tenant() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    plan_keys: list[str] = [platform_key]
    try:
        first = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="dup",
            name="First",
            price_amount=0,
            price_currency="USD",
        )
        plan_keys.append(first.underlying_plan_key)
        with pytest.raises(BillingConflictError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="dup",
                name="Second",
                price_amount=0,
                price_currency="USD",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


# --- Immutability of commercial terms ---------------------------------------------


def test_update_resale_plan_only_changes_display_metadata() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    plan_keys: list[str] = [platform_key]
    try:
        plan = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="rename-me",
            name="Old Name",
            price_amount=100,
            price_currency="USD",
            entitlements={"max_users": 1},
        )
        plan_keys.append(plan.underlying_plan_key)
        updated = update_resale_plan(owner.id, agency.tenant_id, plan.id, name="New Name")
        assert updated.name == "New Name"
        assert updated.price_amount == 100
        assert updated.entitlements == {"max_users": 1}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


def test_deactivate_resale_plan() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    plan_keys: list[str] = [platform_key]
    try:
        plan = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="going-away",
            name="Going Away",
            price_amount=0,
            price_currency="USD",
        )
        plan_keys.append(plan.underlying_plan_key)
        deactivated = deactivate_resale_plan(owner.id, agency.tenant_id, plan.id)
        assert deactivated.status == "disabled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)


# --- Tenant isolation ------------------------------------------------------------


def test_resale_plans_are_isolated_across_reseller_tenants() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    platform_key = _give_agency_a_platform_subscription(
        owner_a.id, agency_a.tenant_id, {"max_users": 5}
    )
    plan_keys = [platform_key]
    try:
        plan = create_resale_plan(
            owner_a.id,
            agency_a.tenant_id,
            key="mine",
            name="Mine",
            price_amount=0,
            price_currency="USD",
        )
        plan_keys.append(plan.underlying_plan_key)
        with pytest.raises(BillingReferenceNotFoundError):
            get_resale_plan(owner_b.id, agency_b.tenant_id, plan.id)
        listed = list_resale_plans(owner_b.id, agency_b.tenant_id)
        assert all(p.id != plan.id for p in listed)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
        cleanup_global_plan_keys(*plan_keys)


# --- Authorization -------------------------------------------------------------


def test_unrelated_actor_cannot_create_resale_plan() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    try:
        with pytest.raises(BillingAccessDeniedError):
            create_resale_plan(
                unrelated.id,
                agency.tenant_id,
                key="nope",
                name="Nope",
                price_amount=0,
                price_currency="USD",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)
        cleanup_global_plan_keys(platform_key)


def test_member_can_read_but_not_create_resale_plan() -> None:
    """`product/billing/event_handlers.py`'s own grant split: `member`
    gets `read`-only on the resale catalog, never `create`/`update`/
    `deactivate` (a revenue-critical decision reserved for `owner`)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, agency.tenant_id, member.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    plan_keys = [platform_key]
    try:
        plan = create_resale_plan(
            owner.id,
            agency.tenant_id,
            key="viewable",
            name="Viewable",
            price_amount=0,
            price_currency="USD",
        )
        plan_keys.append(plan.underlying_plan_key)
        fetched = get_resale_plan(member.id, agency.tenant_id, plan.id)
        assert fetched.id == plan.id
        with pytest.raises(BillingAccessDeniedError):
            create_resale_plan(
                member.id,
                agency.tenant_id,
                key="denied",
                name="Denied",
                price_amount=0,
                price_currency="USD",
            )
        with pytest.raises(BillingAccessDeniedError):
            deactivate_resale_plan(member.id, agency.tenant_id, plan.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)
        cleanup_global_plan_keys(*plan_keys)


# --- Tenant lifecycle ----------------------------------------------------------


def test_suspended_tenant_denies_resale_plan_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    try:
        transition_tenant_status(agency.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(BillingAccessDeniedError):
            create_resale_plan(
                owner.id,
                agency.tenant_id,
                key="denied",
                name="Denied",
                price_amount=0,
                price_currency="USD",
            )
    finally:
        transition_tenant_status(agency.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key)


# --- Pagination ------------------------------------------------------------


def test_list_resale_plans_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    platform_key = _give_agency_a_platform_subscription(
        owner.id, agency.tenant_id, {"max_users": 5}
    )
    plan_keys = [platform_key]
    try:
        for _ in range(3):
            plan = create_resale_plan(
                owner.id,
                agency.tenant_id,
                key=_name("bulk"),
                name="Bulk",
                price_amount=0,
                price_currency="USD",
            )
            plan_keys.append(plan.underlying_plan_key)
        results = list_resale_plans(owner.id, agency.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(*plan_keys)
