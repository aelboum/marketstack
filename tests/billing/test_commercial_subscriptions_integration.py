"""`product/billing/commercial_subscriptions.py`: B2B2C sponsored
subscriptions over the frozen SaaS-OS `core.billing.commercial
.create_subscription()` contract (docs/ROADMAP.md Phase 15, Step 3). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.

Covers: self-pay (agency, client) and sponsored (agency pays for client)
subscription creation; that entitlements/ownership always land on the
*service* tenant, never the payer; the Scenario 4 boundary (a client
cannot pay for an agency-owned plan while the agency's own merchant is
still `onboarding` -- Step 2's own, deliberate limitation, not worked
around here); dual authorization, both the four required negative
combinations and more; idempotency exactly per `core.idempotency`'s own
contract; and tenant isolation.

Builds its own test-only `provider="fake"` `MerchantAccount` and Catalog
v2 `Plan`, both owned by the platform tenant -- deliberately NOT Step 2's
reactive `provider="stripe"` platform merchant, since `core.billing
.FakeBillingProvider.name == "fake"` and the provider adapter name must
match the merchant's own `provider` field exactly
(`BillingProviderMismatchError` otherwise), and no real Stripe adapter is
configured in this test environment. A `BillingAccount` is itself a
privileged provisioning primitive (`core.billing.get_or_create_
billing_account()` requires `billing.account:manage`, which this
product's own event handlers deliberately never grant to an ordinary
role -- module docstring of `product/billing/commercial_subscriptions.py`
only ever checks `billing.account:charge`), so every `BillingAccount`
below is provisioned directly with `SystemCaller(BILLING_OPERATIONS)`,
mirroring `tests/billing/test_commercial_parties_integration.py`'s own
`_get_or_create_platform_billing_account()` discipline -- the function
under test is only ever `create_commercial_subscription()` itself, called
with a real `UserCaller`-shaped actor id.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from core.authority import SystemAuthority, SystemCaller
from core.billing import (
    BillingAccountNotFoundError,
    CommercialPartyNotActiveError,
    FakeBillingProvider,
    MerchantAccountStatus,
    PlanVisibility,
    SubscriptionNotFoundError,
    create_merchant_account,
    create_owned_plan,
    get_subscription,
    list_subscriptions,
)
from core.idempotency import IdempotencyKeyReusedError
from core.identity.models import User
from core.tenancy import get_tenancy_config
from product.agency.onboarding import accept_client_invitation, invite_client_member
from product.agency.provisioning import provision_agency, provision_client
from product.billing.commercial_subscriptions import (
    create_commercial_subscription,
    get_commercial_subscription,
)
from product.billing.errors import BillingAccessDeniedError
from product.billing.parties import get_or_create_billing_account
from product.billing.permissions import BILLING_ACCOUNT_RESOURCE, SUBSCRIPTION_RESOURCE
from product.platform.provisioning import (
    PLATFORM_TENANT_ID_ENV_VAR,
    PlatformTenant,
    bootstrap_platform_tenant,
)

from tests.billing._cleanup import (
    cleanup_global_plan_keys,
    cleanup_tenant_tree,
    cleanup_users,
    make_user,
)

pytestmark = pytest.mark.integration

_SYSTEM = SystemCaller(SystemAuthority.BILLING_OPERATIONS)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[User, PlatformTenant]]:
    """Mirrors `tests/billing/test_commercial_parties_integration.py`'s
    own `platform` fixture exactly."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    get_tenancy_config.cache_clear()
    owner = make_user()
    platform_tenant = bootstrap_platform_tenant(owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform_tenant.tenant_id))
    get_tenancy_config.cache_clear()
    try:
        yield owner, platform_tenant
    finally:
        get_tenancy_config.cache_clear()
        cleanup_tenant_tree(platform_tenant.tenant_id)
        cleanup_users(owner.id)


@pytest.fixture
def fake_plan(platform: tuple[User, PlatformTenant]) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """A dedicated `provider="fake"` platform merchant (status `active`
    from creation -- no onboarding step needed for a test double) plus one
    `PUBLIC` Catalog v2 plan sold through it. `PUBLIC` visibility keeps
    eligibility (`core.billing.evaluate_plan_eligibility()`) out of every
    test below's own concern -- this module's scope is dual
    *authorization*, not catalog discoverability, which Step 3's own task
    explicitly leaves unexercised beyond "a real, adopted, active-merchant
    plan." Yields `(merchant_account_id, plan_id)`."""
    _owner, platform_tenant = platform
    merchant = create_merchant_account(
        _SYSTEM,
        platform_tenant.tenant_id,
        provider="fake",
        provider_account_ref=_name("fake-merchant"),
        status=MerchantAccountStatus.ACTIVE,
    )
    plan = create_owned_plan(
        _SYSTEM,
        platform_tenant.tenant_id,
        merchant_account_id=merchant.id,
        key=_name("plan"),
        name="Step 3 Test Plan",
        visibility=PlanVisibility.PUBLIC,
    )
    try:
        yield merchant.id, plan.id
    finally:
        cleanup_global_plan_keys(plan.key)


def _agency_and_client(owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency.tenant_id, client.tenant_id


def _client_only_member(agency_owner_id: uuid.UUID, client_tenant_id: uuid.UUID) -> User:
    """A user whose *only* role anywhere is `member` at `client_tenant_id`
    -- the realistic "client-only actor" shape for the negative
    authorization tests below. `provision_client()` deliberately performs
    no first-role bootstrap at the client at all (its own docstring: the
    agency owner's pre-existing `SUBTREE` role already reaches it), so the
    only way to get a user scoped to *just* the client is the real
    invite -> accept chain (`product/agency/onboarding.py`), exactly
    `tests/agency/test_onboarding_integration.py`'s own
    `test_accept_client_invitation_end_to_end_then_assign_starting_role`."""
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


# --- Scenario 1: agency self-pay --------------------------------------------


def test_agency_self_pay_creates_an_active_subscription(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    agency_owner = make_user()
    agency_id = provision_agency(agency_owner.id, _name("agency")).tenant_id
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        view = create_commercial_subscription(
            agency_owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=agency_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.payer_tenant_id == agency_id
        assert view.service_tenant_id == agency_id
        assert view.status == "active"
    finally:
        cleanup_tenant_tree(agency_id)
        cleanup_users(agency_owner.id)


# --- Scenario 3: client self-pay ---------------------------------------------


def test_client_self_pay_creates_an_active_subscription(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            client_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=client_id,
            service_tenant_id=client_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.payer_tenant_id == client_id
        assert view.service_tenant_id == client_id
        assert view.status == "active"
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_client_member_not_only_owner_can_self_pay(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """`_MEMBER_GRANTS` (`product/billing/event_handlers.py`) grants
    `billing.account:charge`/`billing.subscription:create` to `member`,
    not only `owner` -- `accept_client_invitation()`'s own starting-role
    assignment (`product/agency/onboarding.py`) gives an invited client
    user exactly `CLIENT_MEMBER_ROLE_NAME` at the client tenant, so this
    is the realistic self-pay shape for an invited client user, not a
    hypothetical one."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    try:
        billing_account_id = _billing_account_id(
            client.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        view = create_commercial_subscription(
            client_member.id,
            payer_tenant_id=client.tenant_id,
            service_tenant_id=client.tenant_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.service_tenant_id == client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


# --- Scenario 2: agency sponsors client (the point of this phase) ----------


def test_agency_sponsors_client_subscription(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=client_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view.payer_tenant_id == agency_id
        assert view.service_tenant_id == client_id
        assert view.status == "active"
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_sponsored_subscription_entitlements_land_on_service_tenant_only(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Ownership model (ADR-0029): the row -- and so its entitlements --
    is `Subscription.tenant_id == service_tenant_id`, never the payer's.
    `list_subscriptions(agency_id)` must stay empty; the agency never
    "has" a subscription it only pays for."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        view = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=client_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        row = get_subscription(client_id, view.id)
        assert row.tenant_id == client_id
        assert row.payer_tenant_id == agency_id
        assert list_subscriptions(agency_id) == []
        assert len(list_subscriptions(client_id)) == 1
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


# --- Scenario 4: documented boundary, not worked around ---------------------


def test_scenario4_client_cannot_pay_for_still_onboarding_agency_merchant(
    platform: tuple[User, PlatformTenant],
) -> None:
    """A client paying for a plan sold through its *own agency's* merchant
    (Scenario 4) is genuinely blocked by Step 2's own, deliberate design:
    `_ensure_agency_merchant_account()` never reaches `active` on its own
    (no Stripe Connect, module docstring of `product/billing/parties.py`)
    -- so provisioning the client's own `BillingAccount` at the agency's
    merchant fails *before* any subscription could be created, exactly
    `core.billing.get_or_create_billing_account()`'s own
    `require_active_merchant_account()` check. This test documents the
    boundary; it does not force a workaround."""
    from product.billing.parties import _ensure_agency_merchant_account

    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        agency_merchant, _created = _ensure_agency_merchant_account(agency_id)
        assert agency_merchant.status == MerchantAccountStatus.ONBOARDING.value
        with pytest.raises(CommercialPartyNotActiveError):
            get_or_create_billing_account(
                _SYSTEM,
                client_id,
                merchant_tenant_id=agency_id,
                merchant_account_id=agency_merchant.id,
            )
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


# --- Dual authorization: negative cases -------------------------------------


def test_actor_with_no_role_anywhere_is_denied(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, _client_id = _agency_and_client(owner.id)
    stranger = make_user()
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                stranger.id,
                payer_tenant_id=agency_id,
                service_tenant_id=agency_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.resource == BILLING_ACCOUNT_RESOURCE
        assert excinfo.value.action == "charge"
    finally:
        cleanup_tenant_tree(_client_id, agency_id)
        cleanup_users(owner.id, stranger.id)


def test_unrelated_clients_member_cannot_charge_another_agencys_billing_account(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """client_b's own member attempting agency_a as payer -- denied on
    the payer check. Section 9's own first required combination."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a_id, _client_a_id = _agency_and_client(owner_a.id)
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    client_b = provision_client(owner_b.id, agency_b.tenant_id, _name("client-b"))
    try:
        billing_account_id = _billing_account_id(
            agency_a_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                owner_b.id,
                payer_tenant_id=agency_a_id,
                service_tenant_id=client_b.tenant_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == agency_a_id
        assert excinfo.value.resource == BILLING_ACCOUNT_RESOURCE
    finally:
        cleanup_tenant_tree(_client_a_id, agency_a_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_owner_cannot_create_a_subscription_for_an_unrelated_agency(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """agency_a's owner attempting agency_b as service tenant -- denied
    on the service check (payer=agency_a is itself valid). Section 9's
    own second required combination."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a_id, _client_a_id = _agency_and_client(owner_a.id)
    agency_b_id = provision_agency(owner_b.id, _name("agency-b")).tenant_id
    try:
        billing_account_id = _billing_account_id(
            agency_a_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                owner_a.id,
                payer_tenant_id=agency_a_id,
                service_tenant_id=agency_b_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == agency_b_id
        assert excinfo.value.resource == SUBSCRIPTION_RESOURCE
    finally:
        cleanup_tenant_tree(_client_a_id, agency_a_id)
        cleanup_tenant_tree(agency_b_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_only_actor_cannot_charge_its_parent_agency(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """The real negative case for Section 9's third required combination:
    an actor whose *only* role is at the client cannot use the parent
    agency's own `BillingAccount` as payer -- `SUBTREE` never reaches
    upward from a client's own role assignment."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    try:
        billing_account_id = _billing_account_id(
            agency.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                client_member.id,
                payer_tenant_id=agency.tenant_id,
                service_tenant_id=client.tenant_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == agency.tenant_id
        assert excinfo.value.resource == BILLING_ACCOUNT_RESOURCE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


def test_agency_owner_cannot_use_unrelated_agencys_billing_account_to_sponsor_its_own_client(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """agency_a's owner attempting agency_b as payer while client_a is
    the service tenant -- denied (on the payer check, `require()`'s own
    order). Section 9's own fourth required combination."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a_id, client_a_id = _agency_and_client(owner_a.id)
    agency_b_id = provision_agency(owner_b.id, _name("agency-b")).tenant_id
    try:
        billing_account_id = _billing_account_id(
            agency_b_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                owner_a.id,
                payer_tenant_id=agency_b_id,
                service_tenant_id=client_a_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == agency_b_id
        assert excinfo.value.resource == BILLING_ACCOUNT_RESOURCE
    finally:
        cleanup_tenant_tree(client_a_id, agency_a_id)
        cleanup_tenant_tree(agency_b_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_owner_cannot_sponsor_an_unrelated_sibling_client(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """client_a's own owner, paying with client_a's own billing account
    (valid payer check), cannot name an unrelated client_b as the service
    tenant -- denied on the service check."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    client_a = provision_client(owner_a.id, agency_a.tenant_id, _name("client-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    client_b = provision_client(owner_b.id, agency_b.tenant_id, _name("client-b"))
    try:
        billing_account_id = _billing_account_id(
            client_a.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                owner_a.id,
                payer_tenant_id=client_a.tenant_id,
                service_tenant_id=client_b.tenant_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == client_b.tenant_id
        assert excinfo.value.resource == SUBSCRIPTION_RESOURCE
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_only_actor_cannot_sponsor_its_own_parent_agency(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Mirror of the parent-payer case on the service side: an actor
    whose only role is at the client cannot name its own parent agency as
    the *service* tenant either -- `SUBTREE` never reaches upward for
    `billing.subscription:create` any more than it does for
    `billing.account:charge`."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    client_member = _client_only_member(agency_owner.id, client.tenant_id)
    try:
        billing_account_id = _billing_account_id(
            client.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError) as excinfo:
            create_commercial_subscription(
                client_member.id,
                payer_tenant_id=client.tenant_id,
                service_tenant_id=agency.tenant_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
        assert excinfo.value.tenant_id == agency.tenant_id
        assert excinfo.value.resource == SUBSCRIPTION_RESOURCE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id, client_member.id)


def test_cross_branch_client_cannot_be_sponsored_by_unrelated_clients_payer(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """client_a's own member, paying with client_a's own billing account,
    cannot name a totally unrelated branch's client_b2 (a second client
    under a second, unrelated agency) as the service tenant."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_c = make_user()
    agency_a_id, client_a_id = _agency_and_client(owner_a.id)
    agency_c = provision_agency(owner_c.id, _name("agency-c"))
    client_c = provision_client(owner_c.id, agency_c.tenant_id, _name("client-c"))
    try:
        billing_account_id = _billing_account_id(
            client_a_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccessDeniedError):
            create_commercial_subscription(
                owner_a.id,
                payer_tenant_id=client_a_id,
                service_tenant_id=client_c.tenant_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(client_a_id, agency_a_id)
        cleanup_tenant_tree(client_c.tenant_id, agency_c.tenant_id)
        cleanup_users(owner_a.id, owner_c.id)


# --- Idempotency, per core.idempotency's own exact contract ----------------


def test_repeated_call_same_key_replays_the_same_subscription(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        key = _name("idem")
        first = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=client_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=FakeBillingProvider(),
        )
        second = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=client_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=FakeBillingProvider(),
        )
        assert second.id == first.id
        assert len(list_subscriptions(client_id)) == 1
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_repeated_call_creates_no_duplicate_subscription(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, _client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        key = _name("idem")
        for _ in range(3):
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency_id,
                service_tenant_id=agency_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=key,
                provider=FakeBillingProvider(),
            )
        assert len(list_subscriptions(agency_id)) == 1
    finally:
        cleanup_tenant_tree(_client_id, agency_id)
        cleanup_users(owner.id)


def test_reused_key_with_a_different_plan_raises_idempotency_key_reused(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Same `idempotency_key`, same `service_tenant_id`, same payer and
    billing account, but a *different* `plan_id` -- the fingerprint
    (`{plan_id, payer_tenant_id, billing_account_id}`) no longer matches,
    so `core.idempotency` itself refuses the reuse. It can never silently
    reuse another request's subscription for a different plan."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    second_plan = create_owned_plan(
        _SYSTEM,
        platform_tenant.tenant_id,
        merchant_account_id=merchant_id,
        key=_name("plan2"),
        name="Step 3 Second Test Plan",
        visibility=PlanVisibility.PUBLIC,
    )
    owner = make_user()
    agency_id, _client_id = _agency_and_client(owner.id)
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        key = _name("idem")
        create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=agency_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=FakeBillingProvider(),
        )
        with pytest.raises(IdempotencyKeyReusedError):
            create_commercial_subscription(
                owner.id,
                payer_tenant_id=agency_id,
                service_tenant_id=agency_id,
                billing_account_id=billing_account_id,
                plan_id=second_plan.id,
                idempotency_key=key,
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(_client_id, agency_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(second_plan.key)


def test_same_key_different_service_tenant_is_an_independent_reservation(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """`core.idempotency` reservations are keyed by
    `(tenant_id, operation, idempotency_key)` -- `tenant_id` there is the
    *service* tenant (`_create_commercial_subscription()`'s own
    `tenant_session_scope(service_tenant_id)`), so the identical key reused
    for a different `service_tenant_id` is an entirely separate
    reservation, never a collision, even with the same payer and plan.
    One shared `FakeBillingProvider` instance is used for both calls here
    -- reusing the same `billing_account_id` across two real (non-replay)
    creations reuses its one stored `provider_customer_ref` too
    (`core/billing/commercial.py::_ensure_provider_customer()`), which
    only the provider instance that minted it still recognizes."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    provider = FakeBillingProvider()
    try:
        agency_billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        key = _name("idem")
        self_pay = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=agency_id,
            billing_account_id=agency_billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=provider,
        )
        sponsored = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=client_id,
            billing_account_id=agency_billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=provider,
        )
        assert self_pay.id != sponsored.id
        assert self_pay.service_tenant_id == agency_id
        assert sponsored.service_tenant_id == client_id
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_idempotency_is_authorized_before_it_is_ever_consulted(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Authorization (`_commercial_context()`) runs *before*
    `begin_idempotent_operation()` is ever reached (verified directly
    against the frozen `core/billing/commercial.py`) -- so an unauthorized
    retry with a previously-successful key can never replay or leak
    another tenant's subscription; it is denied exactly like a first
    attempt would be, with no idempotency state created or consulted for
    the unauthorized actor at all."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency_id, _client_id = _agency_and_client(owner.id)
    stranger = make_user()
    try:
        billing_account_id = _billing_account_id(
            agency_id, merchant_tenant_id=platform_tenant.tenant_id, merchant_account_id=merchant_id
        )
        key = _name("idem")
        real = create_commercial_subscription(
            owner.id,
            payer_tenant_id=agency_id,
            service_tenant_id=agency_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=key,
            provider=FakeBillingProvider(),
        )
        with pytest.raises(BillingAccessDeniedError):
            create_commercial_subscription(
                stranger.id,
                payer_tenant_id=agency_id,
                service_tenant_id=agency_id,
                billing_account_id=billing_account_id,
                plan_id=plan_id,
                idempotency_key=key,
                provider=FakeBillingProvider(),
            )
        assert len(list_subscriptions(agency_id)) == 1
        assert list_subscriptions(agency_id)[0].id == real.id
    finally:
        cleanup_tenant_tree(_client_id, agency_id)
        cleanup_users(owner.id, stranger.id)


# --- Isolation ----------------------------------------------------------


def test_get_commercial_subscription_denies_an_actor_with_no_role_at_all(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    stranger = make_user()
    agency_a_id, _client_a_id = _agency_and_client(owner_a.id)
    try:
        billing_account_id = _billing_account_id(
            agency_a_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        view = create_commercial_subscription(
            owner_a.id,
            payer_tenant_id=agency_a_id,
            service_tenant_id=agency_a_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        with pytest.raises(BillingAccessDeniedError):
            get_commercial_subscription(stranger.id, agency_a_id, view.id)
    finally:
        cleanup_tenant_tree(_client_a_id, agency_a_id)
        cleanup_users(owner_a.id, stranger.id)


def test_get_commercial_subscription_is_a_non_enumerating_404_for_another_tenants_id(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """owner_b is fully authorized to *read* at their own tenant
    (`agency_b_id`) -- so this is not a `require()` denial at all. Naming
    agency_a's own subscription id while scoped to agency_b is "not
    found," never "found but belongs to someone else"
    (`core.billing.get_subscription()`'s own RLS-scoped lookup)."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a_id, _client_a_id = _agency_and_client(owner_a.id)
    agency_b_id = provision_agency(owner_b.id, _name("agency-b")).tenant_id
    try:
        billing_account_id = _billing_account_id(
            agency_a_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        view = create_commercial_subscription(
            owner_a.id,
            payer_tenant_id=agency_a_id,
            service_tenant_id=agency_a_id,
            billing_account_id=billing_account_id,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        with pytest.raises(SubscriptionNotFoundError):
            get_commercial_subscription(owner_b.id, agency_b_id, view.id)
    finally:
        cleanup_tenant_tree(_client_a_id, agency_a_id)
        cleanup_tenant_tree(agency_b_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_billing_account_id_is_scoped_to_its_own_payer_tenant(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Naming agency_b's own `billing_account_id` while authorized (and
    self-paying) as agency_a is not a payer-check bypass: `core.billing`
    resolves `billing_account_id` under the payer tenant's own RLS scope,
    so an id that belongs to a different tenant is simply not found --
    never "found but belongs to someone else." Proves `billing_account_id`
    is tenant-scoped, not just any syntactically valid UUID."""
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner_a = make_user()
    owner_b = make_user()
    agency_a_id, _client_a_id = _agency_and_client(owner_a.id)
    agency_b_id = provision_agency(owner_b.id, _name("agency-b")).tenant_id
    try:
        agency_b_billing_account_id = _billing_account_id(
            agency_b_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        with pytest.raises(BillingAccountNotFoundError):
            create_commercial_subscription(
                owner_a.id,
                payer_tenant_id=agency_a_id,
                service_tenant_id=agency_a_id,
                billing_account_id=agency_b_billing_account_id,
                plan_id=plan_id,
                idempotency_key=_name("idem"),
                provider=FakeBillingProvider(),
            )
    finally:
        cleanup_tenant_tree(_client_a_id, agency_a_id)
        cleanup_tenant_tree(agency_b_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_sibling_clients_self_pay_independently_and_in_isolation(
    platform: tuple[User, PlatformTenant], fake_plan: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _owner, platform_tenant = platform
    merchant_id, plan_id = fake_plan
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_1 = provision_client(owner.id, agency.tenant_id, _name("client-1"))
    client_2 = provision_client(owner.id, agency.tenant_id, _name("client-2"))
    try:
        account_1 = _billing_account_id(
            client_1.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        account_2 = _billing_account_id(
            client_2.tenant_id,
            merchant_tenant_id=platform_tenant.tenant_id,
            merchant_account_id=merchant_id,
        )
        view_1 = create_commercial_subscription(
            owner.id,
            payer_tenant_id=client_1.tenant_id,
            service_tenant_id=client_1.tenant_id,
            billing_account_id=account_1,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        view_2 = create_commercial_subscription(
            owner.id,
            payer_tenant_id=client_2.tenant_id,
            service_tenant_id=client_2.tenant_id,
            billing_account_id=account_2,
            plan_id=plan_id,
            idempotency_key=_name("idem"),
            provider=FakeBillingProvider(),
        )
        assert view_1.id != view_2.id
        assert [s.id for s in list_subscriptions(client_1.tenant_id)] == [view_1.id]
        assert [s.id for s in list_subscriptions(client_2.tenant_id)] == [view_2.id]
    finally:
        cleanup_tenant_tree(client_1.tenant_id, client_2.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
