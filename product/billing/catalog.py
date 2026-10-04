"""Catalog v2 owned plans and plan offers (docs/ROADMAP.md Phase 16, Step
4) -- the Marketstack service-level wrapper over the frozen SaaS-OS
`core.billing.catalog` contract, plus the one-time legacy-plan-adoption
bridge that closes Step 1's own documented `plan_key`/`resale_plan_id`
regression.

**Two independent things live in this module.**

1. `create_owned_plan()`/`create_plan_offer()`/`get_owned_plan()`/
   `set_plan_visibility()`: thin, authorized wrappers over `core.billing
   .catalog.create_owned_plan()`/`create_plan_offer()`/`list_plans()`/
   `set_plan_visibility()` -- the forward-looking, correctly
   modelled path (ADR-0029's own ownership invariant: a plan's owner and
   its merchant are always the SAME tenant, enforced by the frozen
   `fk_billing_plans_owner_merchant` composite foreign key). A tenant
   calling these needs its OWN `MerchantAccount` (`product/billing
   /parties.py`), and that account must be `active` before any
   subscription against the resulting plan can ever be eligible
   (`core.billing.evaluate_plan_eligibility()`) -- exactly Step 2/3's own
   documented Scenario-4 boundary: an agency's own merchant stays
   `onboarding` forever absent real Stripe Connect (explicitly out of
   this phase's scope too), so an agency-OWNED plan built through these
   functions is real and correctly modelled, but not yet eligible for
   any subscription until that boundary is separately closed. These
   functions do not work around that -- they are the correct primitive
   for the day it is.

2. `ensure_legacy_plan_adopted()` (plus its own private merchant helper):
   the actual fix for the plan_key/resale_plan_id gap. Every plan this
   product creates today -- the global "platform plan" catalog
   (`product/billing/subscriptions.py::create_platform_subscription()`'s
   own caller-supplied key) and every `ResalePlan`'s own
   `underlying_plan_key` (`product/billing/resale_plans.py
   ::create_resale_plan()`) -- is still created through the LEGACY,
   unowned `core.billing.create_plan()` (never `create_owned_plan()`
   above): the real payee for every one of these, today, is the single
   deployment-wide default provider `core.billing.service._default_provider()`
   resolves to (the configured `STRIPE_API_KEY` account) -- there is no
   per-reseller Stripe Connect sub-account yet, so a reseller does not,
   today, truthfully own a distinct merchant relationship for its resale
   plans' underlying `core.billing.Plan` the way `create_owned_plan()`
   above requires. `list_plans()` -- the one function that can resolve a
   `plan_id` back to its `key` (`core.billing` exposes no `get_plan_by_id()`)
   -- only ever returns *adopted* plans (`Plan.owner_tenant_id IS NOT
   NULL`) that are also *eligible*, which in turn requires an `active`
   merchant. `adopt_legacy_plan()` is the frozen contract's own, explicit
   bridge for exactly this shape: it gives an already-created, unowned
   legacy plan an owner and a merchant without creating a second plan or
   touching its key (it "keeps its key and stays in the legacy key
   namespace, so legacy key-addressed callers keep resolving it,"
   `core/billing/catalog.py`'s own module docstring) -- so a plan can be
   both legacy-key-addressable (`core.billing.get_plan(key)`,
   `subscribe_idempotent()`) and Catalog-v2-eligible (`list_plans()`)
   at once. `ensure_legacy_plan_adopted()` calls it exactly once per
   plan (idempotently, see its own docstring), under a dedicated,
   explicitly-labelled `provider="legacy"` `MerchantAccount` created
   `active` at creation -- NOT one of Step 2's own `"stripe"`-provider
   commercial-party merchants (`product/billing/parties.py`), and never
   confused for one. This merchant grants no new payment capability and
   represents no Stripe Connect identity; it only lets Catalog v2's own
   bookkeeping correctly recognize a fact that was already true the
   moment `_default_provider()` first confirmed the subscription: *some*
   tenant is the economic owner-of-record for this specific legacy plan
   row, and, absent real per-reseller settlement, that is, truthfully,
   whichever tenant first used it -- visibility is always `public` (any
   tenant may already self-serve a platform plan; a resale plan's real
   recipient restriction is, and remains, enforced entirely by
   `product/billing/resale_plans.py`'s own ancestor-chain lookups, never
   by this adoption)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.billing import (
    DuplicateMerchantAccountError,
    MerchantAccountStatus,
    Plan,
    PlanVisibility,
    adopt_legacy_plan,
    create_merchant_account,
    get_plan,
    list_merchant_accounts,
    list_plans,
)
from core.billing import create_owned_plan as _create_owned_plan
from core.billing import create_plan_offer as _create_plan_offer
from core.billing import set_plan_visibility as _set_plan_visibility
from core.billing.errors import LegacyPlanAdoptionError
from core.billing.models import MerchantAccount, PlanOffer

from product.billing.permissions import BILLING_CATALOG_RESOURCE, require

#: The frozen contract's own bridge accepts only this one system purpose
#: (`core/billing/catalog.py::adopt_legacy_plan()`'s own docstring).
_BILLING_SYSTEM_CALLER = SystemCaller(SystemAuthority.BILLING_OPERATIONS)

#: Deliberately distinct from Step 2's own `"stripe"` commercial-party
#: merchants (`product/billing/parties.py`) -- see module docstring,
#: point 2. Never returned by `get_platform_merchant_account()`/
#: `get_agency_merchant_account()`; this provider name exists only so a
#: legacy-adopted plan's merchant can be `active` without a real Stripe
#: Connect identity.
_LEGACY_CATALOG_PROVIDER = "legacy"


@dataclass(frozen=True, slots=True)
class OwnedPlanView:
    id: uuid.UUID
    owner_tenant_id: uuid.UUID
    merchant_account_id: uuid.UUID
    key: str
    name: str
    entitlements: dict
    visibility: str
    status: str
    created_at: datetime
    updated_at: datetime


def _plan_view(plan: Plan) -> OwnedPlanView:
    assert plan.owner_tenant_id is not None
    assert plan.merchant_account_id is not None
    return OwnedPlanView(
        id=plan.id,
        owner_tenant_id=plan.owner_tenant_id,
        merchant_account_id=plan.merchant_account_id,
        key=plan.key,
        name=plan.name,
        entitlements=plan.entitlements,
        visibility=plan.visibility,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@dataclass(frozen=True, slots=True)
class PlanOfferView:
    id: uuid.UUID
    owner_tenant_id: uuid.UUID
    plan_id: uuid.UUID
    service_tenant_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


def _offer_view(offer: PlanOffer) -> PlanOfferView:
    return PlanOfferView(
        id=offer.id,
        owner_tenant_id=offer.tenant_id,
        plan_id=offer.plan_id,
        service_tenant_id=offer.service_tenant_id,
        status=offer.status,
        created_at=offer.created_at,
        updated_at=offer.updated_at,
    )


def create_owned_plan(
    actor_user_id: uuid.UUID,
    owner_tenant_id: uuid.UUID,
    *,
    merchant_account_id: uuid.UUID,
    key: str,
    name: str,
    entitlements: dict[str, object] | None = None,
    visibility: PlanVisibility = PlanVisibility.PUBLIC,
) -> OwnedPlanView:
    """Create a Catalog v2 plan owned by `owner_tenant_id`, sold by its
    own `merchant_account_id` (module docstring, point 1 -- the frozen
    `fk_billing_plans_owner_merchant` constraint means this must already
    be one of `owner_tenant_id`'s own merchants; `product/billing
    /parties.py::get_platform_merchant_account()`/
    `get_agency_merchant_account()` resolve it). Authorizes
    `billing.catalog:manage` on `owner_tenant_id` first (`product/billing
    /event_handlers.py`'s own `owner`-only grant), then delegates to
    `core.billing.catalog.create_owned_plan()`, which re-validates
    everything else (the key is unique among the owner's own plans;
    `DuplicateOwnedPlanKeyError` propagates unwrapped, exactly
    `product/billing/commercial_subscriptions.py`'s own "product
    authorizes, then delegates to an already-audited SaaS-OS function"
    discipline)."""
    require(actor_user_id, owner_tenant_id, resource=BILLING_CATALOG_RESOURCE, action="manage")
    plan = _create_owned_plan(
        UserCaller(actor_user_id),
        owner_tenant_id,
        merchant_account_id=merchant_account_id,
        key=key,
        name=name,
        entitlements=entitlements,
        visibility=visibility,
    )
    return _plan_view(plan)


def create_plan_offer(
    actor_user_id: uuid.UUID,
    owner_tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    service_tenant_id: uuid.UUID,
) -> PlanOfferView:
    """Offer one of `owner_tenant_id`'s own plans to `service_tenant_id`
    -- what makes an `unlisted` plan eligible for that tenant, and only
    that tenant (`core.billing.catalog.create_plan_offer()`'s own
    docstring). Authorizes `billing.catalog:manage` on `owner_tenant_id`
    first; idempotent (an existing active offer is returned unchanged,
    the frozen contract's own behavior, not reimplemented here)."""
    require(actor_user_id, owner_tenant_id, resource=BILLING_CATALOG_RESOURCE, action="manage")
    offer = _create_plan_offer(
        UserCaller(actor_user_id), owner_tenant_id, plan_id, service_tenant_id=service_tenant_id
    )
    return _offer_view(offer)


def set_plan_visibility(
    actor_user_id: uuid.UUID,
    owner_tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    visibility: PlanVisibility,
) -> OwnedPlanView:
    """Change who may discover and buy one of `owner_tenant_id`'s own
    plans. Authorizes `billing.catalog:manage` on `owner_tenant_id`
    first -- an unrelated tenant (no role there at all) is denied here,
    never reaching `core.billing.catalog.set_plan_visibility()`'s own
    `CatalogPlanNotFoundError` for a plan id it does not own."""
    require(actor_user_id, owner_tenant_id, resource=BILLING_CATALOG_RESOURCE, action="manage")
    plan = _set_plan_visibility(UserCaller(actor_user_id), owner_tenant_id, plan_id, visibility)
    return _plan_view(plan)


def get_owned_plan(
    actor_user_id: uuid.UUID, owner_tenant_id: uuid.UUID, plan_id: uuid.UUID
) -> OwnedPlanView | None:
    """Retrieve one of `owner_tenant_id`'s own plans by id, or `None` if
    it does not exist or is not eligible for `owner_tenant_id` itself
    (e.g. a different tenant's private plan). Built on `list_plans()`
    (`caller, *, service_tenant_id`) -- the frozen contract exposes no
    direct `get_plan(id)` for an owned plan (module docstring, point 2);
    `service_tenant_id=owner_tenant_id` mirrors `product/billing
    /subscriptions.py::_resolve_plan_key()`'s own established "scan the
    one function that can resolve an id" pattern. Authorizes nothing
    beyond what `list_plans()` itself requires (`billing.subscription
    :create` at `owner_tenant_id`) -- the same non-enumerating shape
    every other `product/billing/*.py` read already has: a plan this
    tenant cannot see is indistinguishable from one that does not
    exist."""
    for plan in list_plans(UserCaller(actor_user_id), service_tenant_id=owner_tenant_id):
        if plan.id == plan_id:
            return _plan_view(plan)
    return None


def _find_legacy_catalog_merchant(owner_tenant_id: uuid.UUID) -> MerchantAccount | None:
    ref = _legacy_catalog_provider_account_ref(owner_tenant_id)
    for existing in list_merchant_accounts(owner_tenant_id):
        if existing.provider == _LEGACY_CATALOG_PROVIDER and existing.provider_account_ref == ref:
            return existing
    return None


def _legacy_catalog_provider_account_ref(owner_tenant_id: uuid.UUID) -> str:
    return f"legacy-catalog:{owner_tenant_id}"


def _ensure_legacy_catalog_merchant(owner_tenant_id: uuid.UUID) -> MerchantAccount:
    """Idempotent get-or-create of `owner_tenant_id`'s own `provider
    ="legacy"` merchant (module docstring, point 2) -- mirrors
    `product/billing/parties.py::_ensure_merchant_account()`'s own
    find-then-create-then-handle-the-race shape, duplicated rather than
    imported: that helper is hardcoded to Step 2's own `"stripe"`
    provider constant and this is a deliberately different, narrower
    concept (module docstring) that module's own trust boundary should
    not be widened to also cover."""
    existing = _find_legacy_catalog_merchant(owner_tenant_id)
    if existing is not None:
        return existing
    ref = _legacy_catalog_provider_account_ref(owner_tenant_id)
    try:
        return create_merchant_account(
            _BILLING_SYSTEM_CALLER,
            owner_tenant_id,
            provider=_LEGACY_CATALOG_PROVIDER,
            provider_account_ref=ref,
            status=MerchantAccountStatus.ACTIVE,
        )
    except DuplicateMerchantAccountError:
        existing = _find_legacy_catalog_merchant(owner_tenant_id)
        if existing is None:
            raise
        return existing


def ensure_legacy_plan_adopted(plan_key: str, owner_tenant_id: uuid.UUID) -> Plan:
    """Adopt the legacy plan named `plan_key` into `owner_tenant_id`'s
    own Catalog v2 catalog (`visibility=public`) if no tenant has adopted
    it yet; otherwise return it unchanged (module docstring, point 2).

    Internal bridge, `SystemCaller(BILLING_OPERATIONS)` only -- never
    exposed to a route, job, or other entry point that accepts a tenant
    id from caller-controlled input. `owner_tenant_id` here is always
    either the self-pay tenant itself
    (`product/billing/subscriptions.py::create_platform_subscription()`/
    `change_subscription_plan()`) or the reseller that just created this
    exact plan (`product/billing/resale_plans.py::create_resale_plan()`)
    -- never a caller-supplied value naming an unrelated tenant.

    A plan key shared by many self-pay callers (the realistic "platform
    plan" shape: many tenants self-serving the identical global plan) is
    adopted by whichever tenant calls this first; `public` visibility
    then makes it eligible -- and so resolvable by `product/billing
    /subscriptions.py::_resolve_plan_key()`'s own `list_plans()` scan --
    for every other tenant too, without a second adoption (`core.billing
    .evaluate_plan_eligibility()`'s own `public` rule: eligibility never
    depends on *who* owns a `public` plan, only that its owner's merchant
    is `active`). A concurrent first adoption of the same plan is handled
    by re-reading it, never retried against a different owner."""
    plan = get_plan(plan_key)
    if plan.owner_tenant_id is not None:
        return plan
    merchant = _ensure_legacy_catalog_merchant(owner_tenant_id)
    try:
        return adopt_legacy_plan(
            _BILLING_SYSTEM_CALLER,
            plan.id,
            owner_tenant_id=owner_tenant_id,
            merchant_account_id=merchant.id,
            visibility=PlanVisibility.PUBLIC,
        )
    except LegacyPlanAdoptionError:
        return get_plan(plan_key)


__all__ = [
    "OwnedPlanView",
    "PlanOfferView",
    "create_owned_plan",
    "create_plan_offer",
    "ensure_legacy_plan_adopted",
    "get_owned_plan",
    "set_plan_visibility",
]
