"""`product/billing/parties.py`: `MerchantAccount`/`BillingAccount`
provisioning over the frozen SaaS-OS `core.billing.parties` contract
(docs/ROADMAP.md Phase 14, B2B2C Billing Foundation -- Step 2). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.

Covers: platform-merchant idempotency, agency-merchant idempotency and
isolation, billing-account creation/idempotency/merchant-association/
isolation, and -- the point of this whole phase -- that tenant hierarchy
(agency parent / client child) never implies commercial ownership
(payer, merchant) on its own.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from core.billing import (
    BillingAccountNotFoundError,
    MerchantAccountNotFoundError,
    MerchantAccountStatus,
    get_billing_account,
    get_merchant_account,
    list_billing_accounts,
    list_merchant_accounts,
)
from core.identity.models import User
from core.tenancy import get_platform_tenant_id, get_tenancy_config
from product.agency.provisioning import provision_agency, provision_client

# _ensure_platform_merchant_account/_ensure_agency_merchant_account/
# _get_or_create_platform_billing_account are deliberately underscore-
# prefixed, internal provisioning primitives (independent audit
# remediation -- see product/billing/parties.py's own "Trust boundary"
# docstring section). This test file white-box-tests them directly on
# purpose: it is one of the two authorized internal callers the trust
# boundary itself names (the other being product/billing/
# event_handlers.py's own platform.role_provisioned subscription).
from product.billing.parties import (
    _ensure_agency_merchant_account,
    _ensure_platform_merchant_account,
    _get_or_create_platform_billing_account,
    get_agency_merchant_account,
    get_platform_merchant_account,
)
from product.platform.provisioning import (
    PLATFORM_TENANT_ID_ENV_VAR,
    PlatformTenant,
    bootstrap_platform_tenant,
)

from tests.billing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[User, PlatformTenant]]:
    """Bootstraps a real platform tenant -- `bootstrap_platform_tenant()`
    itself publishes `platform.role_provisioned`, so this fixture's own
    platform tenant already has its `MerchantAccount` provisioned
    reactively by the time it yields (proven directly by
    `test_bootstrapping_the_platform_provisions_its_merchant_reactively`
    below; every other test here just uses the result).
    `get_tenancy_config.cache_clear()` after `monkeypatch.setenv()` --
    `core.tenancy.get_platform_tenant_id()` (`@lru_cache`) is what
    `product/billing/parties.py::get_platform_merchant_account()`/
    `_get_or_create_platform_billing_account()` call; its own docstring
    requires this exact pairing, unlike `product.platform`'s own
    `_configured_platform_tenant_id()`, which reads `os.environ` directly
    and needs no cache-clear (confirmed by reading both directly)."""
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


def _agency_and_client(owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency.tenant_id, client.tenant_id


# --- Platform merchant --------------------------------------------------


def test_bootstrapping_the_platform_provisions_its_merchant_reactively(
    platform: tuple[User, PlatformTenant],
) -> None:
    """End-to-end proof of the event wiring (module docstring): nothing
    in this test calls `_ensure_platform_merchant_account()` directly --
    `bootstrap_platform_tenant()`'s own `platform.role_provisioned` event
    already did."""
    _owner, platform_tenant = platform
    merchants = list_merchant_accounts(platform_tenant.tenant_id)
    assert len(merchants) == 1
    assert merchants[0].status == MerchantAccountStatus.ACTIVE.value


def test_platform_merchant_can_be_provisioned(platform: tuple[User, PlatformTenant]) -> None:
    _owner, platform_tenant = platform
    view, created = _ensure_platform_merchant_account(platform_tenant.tenant_id)
    assert created is False  # already provisioned reactively by the fixture
    assert view.tenant_id == platform_tenant.tenant_id
    assert view.status == MerchantAccountStatus.ACTIVE.value


def test_repeated_platform_merchant_provisioning_is_idempotent(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    first, _ = _ensure_platform_merchant_account(platform_tenant.tenant_id)
    second, created = _ensure_platform_merchant_account(platform_tenant.tenant_id)
    assert created is False
    assert second.id == first.id


def test_repeated_platform_merchant_provisioning_creates_no_duplicate(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    for _ in range(3):
        _ensure_platform_merchant_account(platform_tenant.tenant_id)
    assert len(list_merchant_accounts(platform_tenant.tenant_id)) == 1


def test_get_platform_merchant_account_resolves_via_core_tenancy(
    platform: tuple[User, PlatformTenant],
) -> None:
    """`get_platform_merchant_account()` resolves the platform tenant via
    `core.tenancy.get_platform_tenant_id()` (module docstring), not any
    Marketstack-local constant -- proven here by relying on the fixture's
    own `monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, ...)` alone."""
    _owner, platform_tenant = platform
    assert get_platform_tenant_id() == platform_tenant.tenant_id
    merchant = get_platform_merchant_account()
    assert merchant is not None
    assert merchant.tenant_id == platform_tenant.tenant_id


# --- Agency merchant ------------------------------------------------------


def test_agency_merchant_can_be_provisioned() -> None:
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        view, created = _ensure_agency_merchant_account(agency_id)
        assert created is True
        assert view.tenant_id == agency_id
        assert view.status == MerchantAccountStatus.ONBOARDING.value
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_provisioning_a_new_agency_does_not_provision_a_merchant_automatically() -> None:
    """`_ensure_agency_merchant_account()` is deliberately NOT wired to
    `agency.role_provisioned` (`product/billing/event_handlers.py`'s own
    module docstring: doing so broke every unrelated test suite's own
    tenant-teardown path) -- `provision_agency()` alone must leave the new
    agency with no `MerchantAccount` at all, until something explicitly
    calls `_ensure_agency_merchant_account()` for it."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        assert list_merchant_accounts(agency.tenant_id) == []
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_repeated_agency_merchant_provisioning_is_idempotent_and_creates_no_duplicate() -> None:
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        first, _ = _ensure_agency_merchant_account(agency_id)
        for _ in range(3):
            again, created = _ensure_agency_merchant_account(agency_id)
            assert created is False
            assert again.id == first.id
        assert len(list_merchant_accounts(agency_id)) == 1
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_agency_a_cannot_access_agency_bs_merchant() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    try:
        merchant_a, _ = _ensure_agency_merchant_account(agency_a.tenant_id)
        merchant_b, _ = _ensure_agency_merchant_account(agency_b.tenant_id)
        assert merchant_a.id != merchant_b.id

        # get_agency_merchant_account() only ever returns the named
        # tenant's own merchant (RLS-scoped core.billing.list_merchant_accounts()
        # underneath) -- agency B's lookup never surfaces agency A's row.
        looked_up_a = get_agency_merchant_account(agency_a.tenant_id)
        looked_up_b = get_agency_merchant_account(agency_b.tenant_id)
        assert looked_up_a is not None
        assert looked_up_b is not None
        assert looked_up_a.id == merchant_a.id
        assert looked_up_b.id == merchant_b.id

        # The underlying SaaS-OS primitive itself refuses the cross-tenant
        # read outright: naming agency A's merchant id under agency B's
        # own tenant scope is "not found", never "found but belongs to
        # someone else" (core/billing/parties.py::get_merchant_account()'s
        # own non-enumerating shape).
        with pytest.raises(MerchantAccountNotFoundError):
            get_merchant_account(agency_b.tenant_id, merchant_a.id)
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_cannot_provision_or_modify_its_parents_merchant() -> None:
    """There is no code path by which a client's own tenant_id reaches
    its parent agency's merchant: `_ensure_agency_merchant_account()` is
    tenant-agnostic by name only -- it never resolves "the parent" of
    whatever tenant_id it is given. Calling it with the *client's* own
    tenant_id (as a hypothetical misuse/attack would have to, since no
    API route or actor-facing entry point exists for this at all --
    Phase 2G) provisions a merchant owned by the CLIENT, never the
    agency, and leaves the agency's own merchant state completely
    unaffected."""
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        agency_merchant, _ = _ensure_agency_merchant_account(agency_id)
        client_merchant, created = _ensure_agency_merchant_account(client_id)

        assert created is True
        assert client_merchant.tenant_id == client_id
        assert client_merchant.id != agency_merchant.id

        # The agency's own merchant is untouched -- still exactly one row,
        # still the same id as before the "client" call.
        agency_merchants = list_merchant_accounts(agency_id)
        assert len(agency_merchants) == 1
        assert agency_merchants[0].id == agency_merchant.id
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_merchant_ownership_is_independent_of_subtree_relationship() -> None:
    """The agency owner's `SUBTREE`-scoped role reaches every permission
    check at the client tenant (`product/agency/provisioning.py
    ::provision_agency()`'s own documented `SUBTREE` grant) -- but
    `_ensure_agency_merchant_account()`/`_ensure_platform_merchant_account()`
    take no actor and perform no `SUBTREE`-reachable authorization check
    at all (module docstring: `SystemCaller(BILLING_OPERATIONS)` only).
    Provisioning the agency's own merchant must not create, reach, or
    affect any merchant for its client, despite the live `SUBTREE` grant
    connecting the two tenants for every *other* permission."""
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        _ensure_agency_merchant_account(agency_id)
        assert get_agency_merchant_account(client_id) is None
        assert list_merchant_accounts(client_id) == []
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


# --- BillingAccount ---------------------------------------------------------


def test_agency_billing_account_can_be_obtained_or_created(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        account, created = _get_or_create_platform_billing_account(agency.tenant_id)
        assert created is True
        assert account.tenant_id == agency.tenant_id
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_repeated_billing_account_creation_is_idempotent(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        first, _ = _get_or_create_platform_billing_account(agency.tenant_id)
        for _ in range(3):
            again, created = _get_or_create_platform_billing_account(agency.tenant_id)
            assert created is False
            assert again.id == first.id
        assert len(list_billing_accounts(agency.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_billing_account_is_associated_with_the_correct_merchant(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        platform_merchant = get_platform_merchant_account()
        assert platform_merchant is not None
        account, _ = _get_or_create_platform_billing_account(agency.tenant_id)
        assert account.merchant_account_id == platform_merchant.id
        assert account.merchant_tenant_id == platform_tenant.tenant_id
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_tenant_a_cannot_access_tenant_bs_billing_account(
    platform: tuple[User, PlatformTenant],
) -> None:
    _owner, platform_tenant = platform
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    try:
        account_a, _ = _get_or_create_platform_billing_account(agency_a.tenant_id)
        account_b, _ = _get_or_create_platform_billing_account(agency_b.tenant_id)
        assert account_a.id != account_b.id

        with pytest.raises(BillingAccountNotFoundError):
            get_billing_account(agency_b.tenant_id, account_a.id)
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_billing_account_ownership_is_not_confused_with_service_tenant_hierarchy(
    platform: tuple[User, PlatformTenant],
) -> None:
    """A client's own self-pay `BillingAccount` names the client as payer
    -- never its parent agency, despite the agency's own `SUBTREE` reach
    into the client for every ordinary permission check."""
    _owner, platform_tenant = platform
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        client_account, _ = _get_or_create_platform_billing_account(client_id)
        assert client_account.tenant_id == client_id
        assert client_account.tenant_id != agency_id
        assert list_billing_accounts(agency_id) == []
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)


def test_agency_parent_relationship_does_not_make_the_agency_payer(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Giving the CLIENT a self-pay `BillingAccount` must not, as a side
    effect, give the agency one too -- `agency is parent of client` never
    implies `agency is automatically payer` (module docstring of
    `product/billing/parties.py`)."""
    _owner, platform_tenant = platform
    owner = make_user()
    agency_id, client_id = _agency_and_client(owner.id)
    try:
        _get_or_create_platform_billing_account(client_id)
        assert list_billing_accounts(agency_id) == []
    finally:
        cleanup_tenant_tree(client_id, agency_id)
        cleanup_users(owner.id)
