"""Commercial billing identity (docs/ROADMAP.md Phase 14, B2B2C Billing
Foundation -- Step 2): `MerchantAccount` (payee) and `BillingAccount`
(payer) provisioning over the installed saas-os `core.billing.parties`.

**Foundation only.** Nothing here creates a subscription
(`core.billing.commercial.create_subscription()`), migrates a plan to
Catalog v2 (`create_owned_plan()`/`create_plan_offer()`), or changes any
existing payer/service-tenant API contract -- `product/billing/
subscriptions.py::create_platform_subscription()`/
`create_resale_subscription()` are unchanged by this module and remain
the only subscription-creation path. Sponsored billing (a payer tenant
different from the service tenant) is a later, separately-scoped phase;
this module only makes the parties -- merchant and billing account --
nameable, so that later phase has real commercial identities to use
instead of inventing them under time pressure.

**Provider is `"stripe"` uniformly** -- the single deployment-wide Stripe
account `core/billing/service.py::_default_provider()` already hardcodes
for every existing self-pay subscription. This module never imports
`stripe` or any provider-specific type (mirrors `product/billing/
__init__.py`'s own "never imports stripe" invariant, verified the same
way: by grep).

**`provider_account_ref` is a Marketstack-generated, deterministic
string** derived from the owner tenant id (`f"platform:{tenant_id}"` /
`f"agency:{tenant_id}"`) -- never a real Stripe account id (no Stripe
Connect exists yet; `docs/ADR/0012-...`'s own "no live payment
processing" boundary, unchanged by this module). This keeps
`core.billing.create_merchant_account()`'s own deployment-wide-unique
`(provider, provider_account_ref)` constraint satisfied deterministically,
so a second call for the same tenant always collides with the first
instead of creating a duplicate -- the same "idempotent via a
deterministic derived key" idiom `product/billing/resale_plans.py
::create_resale_plan()`'s own `underlying_plan_key = f"resale:{resale_plan.id}"`
already establishes. `create_merchant_account()` itself is NOT idempotent
(it raises `DuplicateMerchantAccountError` on a repeat); the `_ensure_*`
helpers below are this module's own idempotent wrapper over it, mirroring
`product/agency/roles.py::_get_or_create_role()`'s identical
list-then-create-if-absent shape.

**Status -- commercial bookkeeping only, not a provider-activation claim.**
The platform `MerchantAccount` is created `ACTIVE` because it is the sole,
deployment-wide default merchant `core/billing/service.py::_default_provider()`
already routes every existing self-pay subscription through today --
`ACTIVE` here only names that existing structural fact inside the new
commercial-parties bookkeeping, it does not assert that a real external
Stripe account is currently configured, live, or verified. **Corrected
from an earlier, inaccurate claim**: this repository configures no
`STRIPE_API_KEY` anywhere (`.env.example` and every `.env*` file checked
directly) -- `provider="stripe"`/`provider_account_ref=f"platform:
{tenant_id}"` are a Marketstack-generated commercial identity, never
proof of a real provider account. Actual provider operations (an actual
charge, a real customer) remain exactly as gated as before this module
existed: `core/billing/service.py::_default_provider()` still fails
closed with a secrets-configuration error at the point of an actual
charge if no key is configured, unchanged by anything here. This module
implements no Stripe Connect, no provider reconciliation, and no new
provider integration of any kind -- `ACTIVE`/`ONBOARDING` are
Marketstack-side commercial-party states only.

An agency merchant is created `ONBOARDING` (`core.billing`'s own default)
and is never promoted to `ACTIVE` here: no Stripe Connect account exists
for any agency yet, so `ONBOARDING` is the honest state, and leaving it
there structurally prevents `get_or_create_billing_account()` (which
requires an `ACTIVE` merchant, `core.billing.require_active_merchant_account()`)
from being usable against an agency merchant until a later, deliberate
phase builds real Connect verification and activates it. That is a
safety property of this phase's own scope boundary, not a gap.

**Wiring -- platform reactive, agency explicit-only (asymmetric, by
design).** `product.billing` never imports `product.agency` or
`product.platform` (module docstring of `product/billing/__init__.py`,
unchanged). `product/billing/event_handlers.py` reacts to
`platform.role_provisioned` (`product/platform/roles.py::
ensure_platform_owner_role()`, fired once from `product/platform/
provisioning.py::bootstrap_platform_tenant()`) to provision the platform's
own merchant account reactively, through the same event-dispatcher path
`product/billing/event_handlers.py` already uses for permission-granting
(`docs/ARCHITECTURE.md` section 2.2) -- `bootstrap_platform_tenant()` has
exactly one call shape in the whole repository, so this is safe.
`_ensure_agency_merchant_account()` is deliberately NOT subscribed to
`agency.role_provisioned`: `provision_agency()` is called by essentially
every integration test in this repository for ordinary, unrelated
fixture setup, each with its own pre-existing tenant-teardown helper that
has no reason to know about a new SaaS-OS table this phase introduces --
reactively creating a `core.billing_merchant_accounts` row on every one
of those calls breaks every one of those unrelated cleanup paths with a
foreign-key violation on tenant deletion (confirmed empirically, not
hypothetically: wiring it this way broke `tests/agency/*`'s and
`tests/platform/*`'s own pre-existing cleanup). `product/billing
/event_handlers.py`'s own module docstring documents this exact
reasoning. Calling `_ensure_agency_merchant_account()` remains this
module's one, idempotent, internal-only entry point -- proven safe to
call for any agency by `tests/billing/test_commercial_parties_integration.py`
-- for whichever later, explicitly-scoped phase decides to trigger it (an
API route, an onboarding step, or a reactive hook limited to that phase's
own narrower event); see "Trust boundary" below for what such a future
caller must do first.

**Caller.** `_ensure_platform_merchant_account()` takes no actor at all --
mirroring `product/agency/roles.py::_get_or_create_role()`'s identical
shape exactly -- because its one call site (the platform event handler
above) has no real principal in scope: `Event.payload` carries only
`role_id`/`role_name`, never an actor id (`product/agency/roles.py
::_publish_role_provisioned()`'s own payload shape, which `product
/platform/roles.py::_publish_role_provisioned()` mirrors). It uses
`SystemCaller(SystemAuthority.BILLING_OPERATIONS)` -- `core.billing`'s own
sanctioned system authority for exactly this "an in-process billing
operation with no human principal" case (`core/billing/authorization.py`'s
own documented purpose for it), verified directly against the frozen SHA:
it is not a bypass invented here, it is the one caller type
`core.billing.create_merchant_account()` itself already accepts in place
of a real, permission-holding user. `_ensure_agency_merchant_account()`
uses the identical system caller for the identical reason, now that it
has no actor-carrying call site of its own either (module docstring,
"Wiring" above). `get_or_create_billing_account()` below, by contrast, is
a thin, caller-accepting pass-through -- a future, real self-service or
sponsored caller supplies whichever `core.authority` caller is actually
correct for that call; this module does not hardcode one for it.

**Trust boundary (independent audit remediation).** `_ensure_platform_merchant_account()`,
`_ensure_agency_merchant_account()`, and `_get_or_create_platform_billing_account()`
are underscore-prefixed and deliberately absent from `__all__` *because*
they hardcode `SystemCaller(BILLING_OPERATIONS)` with no actor parameter
at all -- that caller type makes `core.billing`'s own `can()` check a
no-op (`core/billing/authorization.py::authorize_billing()`), so any code
that calls one of these three functions gets full billing-operations
authority for whichever `tenant_id` it names, with no Marketstack-level
check of its own. That is safe only because every current call site
(the platform event handler, and this phase's own tests) already
supplies a `tenant_id` from a trusted, non-caller-controlled source.
Making them private is this phase's way of keeping that fact impossible
to overlook at a glance; each function's own docstring repeats it. A
future caller that wants to expose equivalent behavior to a route, job,
or less-trusted event must perform its own Marketstack-level
authorization (mirroring `product/billing/resale_plans.py
::create_resale_plan()`'s own `product.billing.permissions.require()`
call *before* it reaches an unauthenticated `core.billing` function) --
never by simply importing one of these three.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.authority import SystemAuthority, SystemCaller
from core.billing import (
    BillingAccount,
    DuplicateMerchantAccountError,
    MerchantAccount,
    MerchantAccountStatus,
    create_merchant_account,
    list_billing_accounts,
    list_merchant_accounts,
)
from core.billing import get_or_create_billing_account as _core_get_or_create_billing_account
from core.tenancy import get_platform_tenant_id

from product.billing.errors import PlatformMerchantNotProvisionedError
from product.billing.permissions import BILLING_ACCOUNT_RESOURCE, require

_PROVIDER = "stripe"
_PLATFORM_REF_PREFIX = "platform"
_AGENCY_REF_PREFIX = "agency"

#: The only caller `_ensure_platform_merchant_account()`/
#: `_ensure_agency_merchant_account()` ever use -- see module docstring.
_BILLING_SYSTEM_CALLER = SystemCaller(SystemAuthority.BILLING_OPERATIONS)


@dataclass(frozen=True, slots=True)
class MerchantAccountView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    provider_account_ref: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BillingAccountView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    merchant_tenant_id: uuid.UUID
    merchant_account_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


def _merchant_view(row: MerchantAccount) -> MerchantAccountView:
    return MerchantAccountView(
        id=row.id,
        tenant_id=row.tenant_id,
        provider=row.provider,
        provider_account_ref=row.provider_account_ref,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _billing_account_view(row: BillingAccount) -> BillingAccountView:
    return BillingAccountView(
        id=row.id,
        tenant_id=row.tenant_id,
        merchant_tenant_id=row.merchant_tenant_id,
        merchant_account_id=row.merchant_account_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _platform_provider_account_ref(tenant_id: uuid.UUID) -> str:
    return f"{_PLATFORM_REF_PREFIX}:{tenant_id}"


def _agency_provider_account_ref(tenant_id: uuid.UUID) -> str:
    return f"{_AGENCY_REF_PREFIX}:{tenant_id}"


def _find_merchant(owner_tenant_id: uuid.UUID, provider_account_ref: str) -> MerchantAccount | None:
    for existing in list_merchant_accounts(owner_tenant_id):
        if existing.provider == _PROVIDER and existing.provider_account_ref == provider_account_ref:
            return existing
    return None


def _ensure_merchant_account(
    owner_tenant_id: uuid.UUID, *, provider_account_ref: str, status: MerchantAccountStatus
) -> tuple[MerchantAccountView, bool]:
    """Idempotent get-or-create over `core.billing.create_merchant_account()`
    (module docstring: not itself idempotent). Returns `(view, created)`."""
    existing = _find_merchant(owner_tenant_id, provider_account_ref)
    if existing is not None:
        return _merchant_view(existing), False
    try:
        merchant = create_merchant_account(
            _BILLING_SYSTEM_CALLER,
            owner_tenant_id,
            provider=_PROVIDER,
            provider_account_ref=provider_account_ref,
            status=status,
        )
    except DuplicateMerchantAccountError:
        # Lost a race to a concurrent provisioning call for the same
        # tenant (two role-provisioned events, or a retry) -- the other
        # caller's row is canonical, mirrors product/billing/parties
        # .py::get_or_create_billing_account()'s own identical race
        # handling in the frozen contract.
        existing = _find_merchant(owner_tenant_id, provider_account_ref)
        if existing is None:
            raise
        return _merchant_view(existing), False
    return _merchant_view(merchant), True


def _ensure_platform_merchant_account(
    platform_tenant_id: uuid.UUID,
) -> tuple[MerchantAccountView, bool]:
    """Internal provisioning primitive. Callers must already be operating
    inside an authorized internal provisioning flow. Never expose this
    helper to a route, job, event, or other entry point that accepts a
    tenant ID from caller-controlled input -- it hardcodes
    `SystemCaller(BILLING_OPERATIONS)` (module docstring, "Trust
    boundary"), which skips `core.billing`'s own real authorization check
    entirely.

    Intended for exactly one caller: `product/billing/event_handlers.py`'s
    own `platform.role_provisioned` subscription, fired once from
    `product/platform/provisioning.py::bootstrap_platform_tenant()`'s
    platform-bootstrap path. Idempotently provisions
    `platform_tenant_id`'s own `MerchantAccount` -- created `ACTIVE`
    (module docstring); safe to call again for the same tenant (returns
    the existing row, `created=False`)."""
    return _ensure_merchant_account(
        platform_tenant_id,
        provider_account_ref=_platform_provider_account_ref(platform_tenant_id),
        status=MerchantAccountStatus.ACTIVE,
    )


def _ensure_agency_merchant_account(
    agency_tenant_id: uuid.UUID,
) -> tuple[MerchantAccountView, bool]:
    """Internal provisioning primitive. Callers must already be operating
    inside an authorized internal provisioning flow. Never expose this
    helper to a route, job, event, or other entry point that accepts a
    tenant ID from caller-controlled input -- it hardcodes
    `SystemCaller(BILLING_OPERATIONS)` (module docstring, "Trust
    boundary"), which skips `core.billing`'s own real authorization check
    entirely.

    This function does NOT determine whether `agency_tenant_id` is
    actually an agency -- it performs no root-tenant check, no "has an
    owner role" check, nothing: it provisions an identical `MerchantAccount`
    for whatever tenant id it is given. It must never be treated as an
    authorization check or as proof that the named tenant is an agency;
    that determination belongs entirely to whichever caller decides to
    invoke this function.

    Idempotently provisions `agency_tenant_id`'s own `MerchantAccount` --
    created `ONBOARDING` (module docstring: no Stripe Connect exists
    yet). Deliberately NOT wired to any event (module docstring,
    "Wiring") -- the only current callers are this phase's own tests;
    safe to call again for the same tenant."""
    return _ensure_merchant_account(
        agency_tenant_id,
        provider_account_ref=_agency_provider_account_ref(agency_tenant_id),
        status=MerchantAccountStatus.ONBOARDING,
    )


def get_platform_merchant_account() -> MerchantAccountView | None:
    """The platform's own `MerchantAccount`, or `None` if
    `_ensure_platform_merchant_account()` has never run for it (a
    deployment whose platform tenant was bootstrapped before this phase
    existed, or where the `platform.role_provisioned` event handler was
    never imported). Resolves the platform tenant the same way
    `core.billing`'s own default Stripe adapter does
    (`core.tenancy.get_platform_tenant_id()`) -- never
    `product.platform`'s own resolver, which this module may not import
    (module docstring: "product.billing never imports... product.platform").
    This read-only lookup is public: it names no caller and performs no
    mutation, so it carries none of the trust-boundary concern the three
    private provisioning primitives do (module docstring, "Trust boundary")."""
    platform_tenant_id = get_platform_tenant_id()
    ref = _platform_provider_account_ref(platform_tenant_id)
    merchant = _find_merchant(platform_tenant_id, ref)
    return _merchant_view(merchant) if merchant is not None else None


def get_agency_merchant_account(agency_tenant_id: uuid.UUID) -> MerchantAccountView | None:
    """`agency_tenant_id`'s own `MerchantAccount`, or `None` if
    `_ensure_agency_merchant_account()` has never run for it. RLS-scoped
    to `agency_tenant_id` by `core.billing.list_merchant_accounts()`
    itself -- there is no way to name a different tenant's merchant
    through this function. Public for the identical reason
    `get_platform_merchant_account()` is: read-only, no caller, no
    mutation."""
    merchant = _find_merchant(agency_tenant_id, _agency_provider_account_ref(agency_tenant_id))
    return _merchant_view(merchant) if merchant is not None else None


def get_or_create_billing_account(
    caller: object,
    payer_tenant_id: uuid.UUID,
    *,
    merchant_tenant_id: uuid.UUID,
    merchant_account_id: uuid.UUID,
) -> tuple[BillingAccountView, bool]:
    """Thin, payer/merchant-agnostic wrapper over `core.billing
    .get_or_create_billing_account()` -- one `BillingAccount` per
    `(payer_tenant_id, merchant_account_id)`, enforced by `core.billing`'s
    own `uq_billing_accounts_tenant_merchant`. Works identically for
    self-pay (`payer_tenant_id` paying at the platform merchant,
    `_get_or_create_platform_billing_account()` below) and, later, for
    sponsored billing (a different payer tenant at an agency's merchant)
    -- this module never conflates the two, and introduces no field or
    assumption that would make them structurally indistinguishable
    (Phase 2E). `caller` is the real `core.authority` caller for
    whichever call site this is -- never hardcoded here."""
    account, created = _core_get_or_create_billing_account(
        caller,
        payer_tenant_id,
        merchant_tenant_id=merchant_tenant_id,
        merchant_account_id=merchant_account_id,
    )
    return _billing_account_view(account), created


def _get_or_create_platform_billing_account(
    tenant_id: uuid.UUID,
) -> tuple[BillingAccountView, bool]:
    """Internal self-pay provisioning convenience -- NOT an authorization
    boundary. Callers must already be operating inside an authorized
    internal provisioning flow. Never expose this helper to a route, job,
    event, or other entry point that accepts a tenant ID from
    caller-controlled input -- it hardcodes `SystemCaller(BILLING_OPERATIONS)`
    (module docstring, "Trust boundary"), which skips `core.billing`'s own
    real authorization check entirely; it does not itself decide whether
    `tenant_id` is allowed to have a billing account created.

    Names `tenant_id`'s own `BillingAccount` at the platform merchant --
    the exact economic relationship every existing self-pay subscription
    already has implicitly (module docstring: the single deployment-wide
    default merchant). This only names that relationship through the new
    commercial-parties primitives; it does not read, create, or change
    any `core.billing.Subscription` row, and `product/billing/
    subscriptions.py`'s existing self-pay path is untouched (Phase 2F).
    No real actor is available at this phase's own call sites (direct
    tests only; nothing in product code calls this yet) -- a future,
    actor-facing caller should use the public, caller-accepting
    `get_or_create_billing_account()` above instead of this convenience,
    once it has its own authorization decision to supply as `caller`."""
    platform_tenant_id = get_platform_tenant_id()
    merchant = get_platform_merchant_account()
    if merchant is None:
        raise PlatformMerchantNotProvisionedError(platform_tenant_id)
    return get_or_create_billing_account(
        _BILLING_SYSTEM_CALLER,
        tenant_id,
        merchant_tenant_id=platform_tenant_id,
        merchant_account_id=merchant.id,
    )


def list_tenant_billing_accounts(
    actor_user_id: uuid.UUID, payer_tenant_id: uuid.UUID
) -> list[BillingAccountView]:
    """`payer_tenant_id`'s own `BillingAccount`s. Authorizes `billing
    .account:read` on `payer_tenant_id` first (B2B2C API Contract
    Expansion, Step 5) -- this function's own previous signature took no
    `actor_user_id` and no authorization at all; safe while its only
    callers were this module's own tests, but not once
    `product/billing/routes.py` exposes it over HTTP (an unauthenticated
    `payer_tenant_id` RLS-scopes to exactly that tenant's own rows, so
    nothing here ever returns a *different* tenant's accounts, but
    nothing previously stopped a caller from simply naming an arbitrary
    `payer_tenant_id` it has no relationship to and reading that
    tenant's own billing accounts). No existing caller in this repository
    called this function before Step 5 (confirmed by reading every
    caller directly), so this is not a breaking change to any real
    integration."""
    require(actor_user_id, payer_tenant_id, resource=BILLING_ACCOUNT_RESOURCE, action="read")
    return [_billing_account_view(row) for row in list_billing_accounts(payer_tenant_id)]


__all__ = [
    "BillingAccountView",
    "MerchantAccountView",
    "get_agency_merchant_account",
    "get_or_create_billing_account",
    "get_platform_merchant_account",
    "list_tenant_billing_accounts",
]
