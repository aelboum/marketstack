"""`product/billing/subscriptions.py`: platform/resale subscription
lifecycle, agency `SUBTREE` administration of a client's subscription,
tenant isolation, idempotency, audit, and events (docs/ROADMAP.md Phase
13.1/13.3). Real disposable Postgres. Marked `integration`, excluded from
the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.billing import PlanNotFoundError, SubscriptionNotFoundError, create_plan
from core.billing.provider import FakeBillingProvider
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.billing.errors import (
    BillingAccessDeniedError,
    BillingReferenceNotFoundError,
    BillingValidationError,
)
from product.billing.resale_plans import create_resale_plan, deactivate_resale_plan
from product.billing.subscriptions import (
    RESALE_SUBSCRIPTION_CREATED_EVENT_TYPE,
    cancel_subscription,
    change_subscription_plan,
    create_platform_subscription,
    create_resale_subscription,
    get_effective_entitlements,
    get_subscription,
    list_subscriptions,
)
from product.foundation.events import subscribe

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


def _platform_plan(entitlements: dict) -> str:
    key = _name("platform-plan")
    create_plan(key, "Throwaway Platform Plan", entitlements=entitlements)
    return key


# --- Platform subscription (13.1, generalized: any tenant may self-serve) -------


def test_create_platform_subscription_valid() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    plan_key = _platform_plan({"max_users": 10})
    try:
        subscription = create_platform_subscription(
            owner.id,
            agency.tenant_id,
            plan_key,
            _name("idem"),
            provider=FakeBillingProvider(),
        )
        assert subscription.tenant_id == agency.tenant_id
        assert subscription.status == "active"
        assert subscription.plan_key == plan_key
        assert subscription.resale_plan_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(plan_key)


def test_create_platform_subscription_is_idempotent_on_retry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    plan_key = _platform_plan({"max_users": 10})
    idem_key = _name("idem")
    try:
        first = create_platform_subscription(
            owner.id, agency.tenant_id, plan_key, idem_key, provider=FakeBillingProvider()
        )
        second = create_platform_subscription(
            owner.id, agency.tenant_id, plan_key, idem_key, provider=FakeBillingProvider()
        )
        assert first.id == second.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(plan_key)


def test_create_platform_subscription_rejects_unknown_plan() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(PlanNotFoundError):
            create_platform_subscription(
                owner.id,
                agency.tenant_id,
                "totally-unknown-plan",
                _name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_platform_subscription() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    plan_key = _platform_plan({"max_users": 10})
    try:
        with pytest.raises(BillingAccessDeniedError):
            create_platform_subscription(
                unrelated.id,
                agency.tenant_id,
                plan_key,
                _name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)
        cleanup_global_plan_keys(plan_key)


def test_suspended_tenant_denies_platform_subscription_creation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    plan_key = _platform_plan({"max_users": 10})
    try:
        transition_tenant_status(agency.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(BillingAccessDeniedError):
            create_platform_subscription(
                owner.id,
                agency.tenant_id,
                plan_key,
                _name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        transition_tenant_status(agency.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(plan_key)


# --- Resale subscription (13.3) --------------------------------------------------


def _agency_with_resale_plan(owner_id, entitlements: dict, resale_entitlements: dict):
    agency, client = _agency_and_client(owner_id)
    platform_key = _platform_plan(entitlements)
    create_platform_subscription(
        owner_id, agency.tenant_id, platform_key, _name("idem"), provider=FakeBillingProvider()
    )
    plan = create_resale_plan(
        owner_id,
        agency.tenant_id,
        key=_name("tier"),
        name="Tier",
        price_amount=0,
        price_currency="USD",
        entitlements=resale_entitlements,
    )
    return agency, client, platform_key, plan


def test_create_resale_subscription_valid_and_entitlements_apply() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        assert subscription.tenant_id == client.tenant_id
        assert subscription.resale_plan_id == plan.id

        entitlements = get_effective_entitlements(owner.id, client.tenant_id)
        assert entitlements == {"max_users": 5}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


def test_create_resale_subscription_publishes_event_and_extra_audit_entry() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    received = []

    def _handler(event):
        received.append(event)

    subscribe(RESALE_SUBSCRIPTION_CREATED_EVENT_TYPE, _handler)
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        matching_events = [
            e for e in received if e.payload.get("subscription_id") == str(subscription.id)
        ]
        assert len(matching_events) == 1
        assert matching_events[0].payload["resale_plan_id"] == str(plan.id)

        entries = list_audit_log(
            client.tenant_id, resource_type="billing.subscription", resource_id=str(subscription.id)
        )
        matching_audit = [e for e in entries if e.action == "billing.resale_subscription.created"]
        assert len(matching_audit) == 1
        # NOTE: the ORM attribute is `entry_metadata` (mapped to the DB
        # column named "metadata") -- `.metadata` on any `Base` subclass
        # is SQLAlchemy's own declarative `MetaData` registry, not this
        # column; using `.metadata` here would silently compare against
        # that registry object instead (see this phase's own
        # implementation/audit report for where this was discovered).
        assert matching_audit[0].entry_metadata == {"resale_plan_id": str(plan.id)}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


def test_create_resale_subscription_rejects_disabled_plan() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    try:
        deactivate_resale_plan(owner.id, agency.tenant_id, plan.id)
        with pytest.raises(BillingValidationError):
            create_resale_subscription(
                owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


def test_create_resale_subscription_rejects_plan_from_unrelated_agency() -> None:
    """A resale plan belonging to an agency that is NOT an ancestor of the
    target tenant must be rejected -- the cross-agency isolation the
    resale model depends on."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a, platform_key_a, plan_a = _agency_with_resale_plan(
        owner_a.id, {"max_users": 50}, {"max_users": 5}
    )
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        with pytest.raises(BillingReferenceNotFoundError):
            create_resale_subscription(
                owner_b.id,
                client_b.tenant_id,
                plan_a.id,
                _name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
        cleanup_global_plan_keys(platform_key_a, plan_a.underlying_plan_key)


# --- Agency SUBTREE administration of a client's subscription --------------------


def test_agency_owner_can_create_and_cancel_clients_subscription_via_subtree() -> None:
    """`product/agency/provisioning.py::provision_agency()`'s own
    SUBTREE-scoped owner role reaches the client tenant automatically --
    no billing-specific authorization code is needed for this."""
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        cancelled = cancel_subscription(
            owner.id, client.tenant_id, subscription.id, provider=FakeBillingProvider()
        )
        assert cancelled.status == "canceled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


def test_client_member_can_self_serve_but_not_cancel() -> None:
    """`product/billing/event_handlers.py`'s own grant split: `member`
    gets `create`/`read`/`update` on subscriptions, never `cancel`."""
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        subscription = create_resale_subscription(
            member.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        fetched = get_subscription(member.id, client.tenant_id, subscription.id)
        assert fetched.id == subscription.id
        with pytest.raises(BillingAccessDeniedError):
            cancel_subscription(member.id, client.tenant_id, subscription.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


# --- Tenant isolation ------------------------------------------------------------


def test_subscriptions_are_isolated_across_sibling_clients() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    other_client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        with pytest.raises(SubscriptionNotFoundError):
            get_subscription(owner.id, other_client.tenant_id, subscription.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, other_client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


# --- Change plan / cancel ---------------------------------------------------------


def test_change_subscription_plan_between_resale_tiers() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    higher_plan = create_resale_plan(
        owner.id,
        agency.tenant_id,
        key=_name("tier"),
        name="Higher Tier",
        price_amount=0,
        price_currency="USD",
        entitlements={"max_users": 20},
    )
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        changed = change_subscription_plan(
            owner.id,
            client.tenant_id,
            subscription.id,
            resale_plan_id=higher_plan.id,
            provider=FakeBillingProvider(),
        )
        assert changed.resale_plan_id == higher_plan.id
        assert get_effective_entitlements(owner.id, client.tenant_id) == {"max_users": 20}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(
            platform_key, plan.underlying_plan_key, higher_plan.underlying_plan_key
        )


def test_change_subscription_plan_rejects_both_sources_supplied() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        with pytest.raises(BillingValidationError):
            change_subscription_plan(
                owner.id,
                client.tenant_id,
                subscription.id,
                platform_plan_key=platform_key,
                resale_plan_id=plan.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)


def test_list_subscriptions() -> None:
    owner = make_user()
    agency, client, platform_key, plan = _agency_with_resale_plan(
        owner.id, {"max_users": 50}, {"max_users": 5}
    )
    try:
        subscription = create_resale_subscription(
            owner.id, client.tenant_id, plan.id, _name("idem"), provider=FakeBillingProvider()
        )
        listed = list_subscriptions(owner.id, client.tenant_id)
        assert any(s.id == subscription.id for s in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)
