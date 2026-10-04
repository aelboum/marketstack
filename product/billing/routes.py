"""The Billing/Resale API (docs/ROADMAP.md Phase 13), mounted under
`/v1/billing` in `product/api/main.py` (Phase 13 API exposure follow-up --
see this module's own package docstring, `product/billing/__init__.py`,
for the exact wiring).

**One frontend, identity-agnostic routes**
(docs/ADR/0012-resale-billing-ownership-model.md): every route below is
named around the resource it operates on (`resale-plans`, `subscriptions`,
`entitlements`), never around an actor identity ("agency"/"client"/
"platform") -- the same authenticated actor + `tenant_id` + `core.rbac
.can()` chokepoint every other module's routes already use decides what
each caller may actually do; the frontend renders whatever capabilities
that produces.

**Ingress dependency choice** -- identical reasoning to
`product/reputation/routes.py`'s own module docstring: every route uses
`api.dependencies.get_current_actor`, never `get_tenant_context()`/
`require_permission()`. Every `product/billing/*.py` service function
performs its own `core.rbac.can()` check via `product.billing.permissions
.require()` before touching any `billing.*` row or calling `core.billing`.

**Non-enumeration**: `BillingAccessDeniedError`, `BillingReferenceNotFoundError`,
and `core.billing`'s own `SubscriptionNotFoundError` all map to the
identical `404` shape `api.errors.not_found()` uses elsewhere.
`BillingValidationError`/`ResaleTierCeilingExceededError`/`core.billing
.InvalidPlanKeyError` map to `400`. `BillingConflictError`/
`core.billing.DuplicatePlanKeyError` map to `409`. `core.billing
.InheritedBillingSubscriptionError`/`InvalidBillingHierarchyError` (a real
tenant billing-configuration conflict, never a client input error) also
map to `409`. `core.billing.BillingProviderError` (the external payment
provider rejected the operation) maps to the same `503` shape
`product/websites/routes.py::_enforce_public_rate_limit()` already uses
for its own backend-unavailable case -- a transient, retryable failure,
never a `400`/`500`.

**Explicit tenant-scoped catalog read** (B2B2C API Contract Expansion,
Step 5 -- replaces the Step 4 interim fix). `GET /tenants/{tenant_id}/plans`
calls `product/billing/catalog.py::list_eligible_plans(actor_id,
tenant_id)`, which authorizes `billing.subscription:read` on `tenant_id`
itself before calling the frozen `core.billing.list_plans(caller, *,
service_tenant_id)` (Catalog v2) as a real `UserCaller` -- never a
`SystemCaller` bypass. This permanently replaces the old, un-scoped
`GET /plans` (Step 4's own interim fix hardcoded the platform tenant as
`service_tenant_id`, which answered "what can the platform tenant see,"
not "what can the calling tenant see" -- a real caller for any OTHER
tenant got the platform's own catalog, never their own). The path now
matches this router's own, universal `{tenant_id}` convention, used by
every other route in this file -- no query parameter was invented. An
unrelated tenant cannot use this to enumerate another tenant's private
catalog: eligibility is evaluated for the path's own `tenant_id`, under
the caller's own real authority there, exactly as `core.billing
.evaluate_plan_eligibility()` already enforces for every other Catalog v2
consumer.

**A genuine, confirmed frozen-contract gap, deliberately not restored**:
the pre-Catalog-v2 contract the *original* `GET /plans` had -- enumerate
literally every legacy plan in the deployment, adopted or not, regardless
of any tenant -- has no Catalog v2 equivalent at all (`core/billing
/catalog.py`'s own module docstring: "there is no unrestricted plan
enumeration"; `core.billing` exposes no function that lists unowned/
unadopted plans). That capability is gone, permanently, by the frozen
contract's own design, not by an oversight here. Plan *creation* is
deliberately not exposed here at all (unchanged).

**SaaS entitlement enforcement** (`product/billing/resale_plans.py
::create_resale_plan()`'s own module docstring): `core.billing
.EntitlementDeniedError` maps to `403` via `api.errors.forbidden()` --
`api.dependencies.require_entitlement_and_quota()`'s own established
status code for this exact error (SaaS-OS's own reference composition of
this identical Entitlement check, not used directly by this router for
the unrelated, pre-existing `SUBTREE`-authorization reason this module's
own "Ingress dependency choice" section above already explains).
Deliberately distinct from this router's own `BillingAccessDeniedError`
(`404`, non-enumerating -- section above): that distinction carries no
cross-tenant enumeration risk here, because an entitlement check only
ever runs against the SAME `tenant_id` a `product.billing.permissions
.require()` RBAC check has already authorized the caller for in this
same request -- unlike a genuine 404 case (a foreign or nonexistent
tenant), there is no "does this other tenant exist" question a `403` vs
`404` distinction could leak; it only ever tells an already-authorized
caller about their OWN tenant's own plan standing. `core.usage
.QuotaExceededError` maps to `429` via `api.errors.quota_exceeded()` --
the same status `api.dependencies`' own quota gate returns, with its own
distinct, fixed `detail` string never conflated with an ordinary rate
limit. Neither error's own `str()` (which names the entitlement key, or
the quota metric plus the tenant's own used/limit figures) is echoed into
the HTTP response -- both use a fixed, generic `detail`, mirroring this
module's own existing `_conflict()` discipline.

**B2B2C commercial subscriptions and billing accounts** (Step 5). Three
new routes expose Step 2/3's own services, unchanged, over HTTP for the
first time:

- `GET /tenants/{tenant_id}/billing-accounts` -- `product/billing
  /parties.py::list_tenant_billing_accounts(actor_id, tenant_id)`
  (payer's own `BillingAccount`s; now authorized -- see that function's
  own docstring for why Step 5 added a check it previously lacked).
- `POST /tenants/{tenant_id}/commercial-subscriptions` -- `product
  /billing/commercial_subscriptions.py::create_commercial_subscription()`,
  unchanged: `payer_tenant_id`/`billing_account_id`/`plan_id` are explicit
  request-body fields, never inferred from `tenant_id` (the path's own
  `tenant_id` is always `service_tenant_id` -- the one and only role this
  router's own `{tenant_id}` already plays for every subscription-shaped
  route, `create_platform_subscription()`/`create_resale_subscription()`
  included). Self-pay is `payer_tenant_id == tenant_id`; sponsored is
  `payer_tenant_id != tenant_id` -- both are the identical request shape,
  and nothing here special-cases either. No `provider` override is
  accepted over HTTP (mirrors the existing `/subscriptions` route's own
  "a caller cannot choose their own payment provider" rule). Dual
  authorization (payer charge + service create) is enforced entirely by
  `create_commercial_subscription()` itself -- this route performs no
  authorization of its own, by design (module docstring, "Ingress
  dependency choice").
- `GET /tenants/{tenant_id}/commercial-subscriptions/{subscription_id}`
  -- `get_commercial_subscription()`, authorized against `tenant_id`
  (the service tenant) only, unchanged.

The pre-existing `/subscriptions` routes (self-pay/resale only, via
`core.billing.subscribe_idempotent()`) are completely unchanged and
untouched -- this is an additive, parallel path, never a replacement; see
`product/billing/commercial_subscriptions.py`'s own module docstring for
why the two paths coexist. No "list commercial subscriptions" route
exists (Step 3 built no `list_commercial_subscriptions()` to expose, and
the existing `GET /tenants/{tenant_id}/subscriptions` already lists every
row in `core.billing_subscriptions` for `tenant_id`, commercial rows
included -- just without `payer_tenant_id`/`billing_account_id`
/`merchant_account_id`, which `SubscriptionView` has never carried; a
richer unified listing is explicitly deferred, not silently dropped).

**New error mappings** (Step 5): `BillingAccountNotFoundError`/`core
.billing.errors.PlanNotEligibleError` (an invalid payer-owned billing
account, or a plan/offer that does not exist, is withdrawn, is owned by
an unrelated tenant, or has no matching offer -- SaaS-OS deliberately
collapses every one of those into the identical, non-enumerating
`PlanNotEligibleError`, so this router maps it the same way it already
maps every other not-found-or-forbidden case) join `_NOT_FOUND_ERRORS`
(`404`). `CommercialPartyNotActiveError`/`LiveSubscriptionExistsError`
(an inactive merchant, or a second live subscription at the same
merchant) join `_CONFLICT_ERRORS` (`409`, via this module's own
`_conflict()`). `core.idempotency.IdempotencyKeyReusedError`/
`IdempotencyInProgressError` map to `api.errors.idempotency_key_reused()`
/`idempotency_in_progress()` -- the frozen SaaS-OS reference API error
shapes for exactly these two cases, `409` with their own distinct, fixed
`detail` strings, never this module's generic `_conflict()`.
`BillingProviderMismatchError`/`BillingProviderContractError` join the
existing `BillingProviderError` bucket (`503`) -- all three are "the
configured provider adapter cannot serve this merchant," never a caller
input error.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import (
    forbidden,
    idempotency_in_progress,
    idempotency_key_reused,
    not_found,
    quota_exceeded,
    service_unavailable,
)
from core.billing import (
    BillingAccountNotFoundError,
    BillingProviderContractError,
    BillingProviderError,
    BillingProviderMismatchError,
    CommercialPartyNotActiveError,
    DuplicatePlanKeyError,
    EntitlementDeniedError,
    InheritedBillingSubscriptionError,
    InvalidBillingHierarchyError,
    InvalidPlanKeyError,
    LiveSubscriptionExistsError,
    PlanNotFoundError,
    SubscriptionNotFoundError,
)
from core.billing.errors import PlanNotEligibleError
from core.idempotency import IdempotencyInProgressError, IdempotencyKeyReusedError
from core.usage import QuotaExceededError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.billing.catalog import OwnedPlanView, list_eligible_plans
from product.billing.commercial_subscriptions import (
    CommercialSubscriptionView,
    create_commercial_subscription,
    get_commercial_subscription,
)
from product.billing.errors import (
    BillingAccessDeniedError,
    BillingConflictError,
    BillingReferenceNotFoundError,
    BillingValidationError,
    ResaleTierCeilingExceededError,
)
from product.billing.models import (
    BILLING_INTERVAL_MONTH,
    MAX_CURRENCY_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_KEY_LENGTH,
    MAX_NAME_LENGTH,
)
from product.billing.parties import BillingAccountView, list_tenant_billing_accounts
from product.billing.resale_plans import (
    ResalePlanView,
    create_resale_plan,
    deactivate_resale_plan,
    get_resale_plan,
    list_available_resale_plans,
    list_resale_plans,
    update_resale_plan,
)
from product.billing.subscriptions import (
    SubscriptionView,
    cancel_subscription,
    change_subscription_plan,
    create_platform_subscription,
    create_resale_subscription,
    get_effective_entitlements,
    get_subscription,
    list_subscriptions,
)

router = APIRouter(prefix="/v1/billing", tags=["billing"])

_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    BillingValidationError,
    ResaleTierCeilingExceededError,
    InvalidPlanKeyError,
)
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    BillingAccessDeniedError,
    BillingReferenceNotFoundError,
    SubscriptionNotFoundError,
    PlanNotFoundError,
    BillingAccountNotFoundError,
    PlanNotEligibleError,
)
_CONFLICT_ERRORS: tuple[type[Exception], ...] = (
    BillingConflictError,
    DuplicatePlanKeyError,
    InheritedBillingSubscriptionError,
    InvalidBillingHierarchyError,
    CommercialPartyNotActiveError,
    LiveSubscriptionExistsError,
)
_PROVIDER_ERRORS: tuple[type[Exception], ...] = (
    BillingProviderError,
    BillingProviderMismatchError,
    BillingProviderContractError,
)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except IdempotencyKeyReusedError:
        raise idempotency_key_reused() from None
    except IdempotencyInProgressError:
        raise idempotency_in_progress() from None
    except _CONFLICT_ERRORS:
        raise _conflict(
            "That billing operation conflicts with the tenant's current state."
        ) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except _PROVIDER_ERRORS:
        raise service_unavailable(5) from None
    except EntitlementDeniedError:
        # Fixed, generic detail (module docstring) -- never str(exc), which
        # names the entitlement key. Same shape and same non-enumeration
        # reasoning as an RBAC denial (api.dependencies
        # .require_entitlement_and_quota()'s own established convention).
        raise forbidden() from None
    except QuotaExceededError:
        # Fixed, generic detail -- never str(exc), which names the metric
        # and the tenant's own used/limit figures.
        raise quota_exceeded() from None


# --- Request bodies ----------------------------------------------------------


class CreateResalePlanRequest(BaseModel):
    key: str = Field(max_length=MAX_KEY_LENGTH)
    name: str = Field(max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    price_amount: int = Field(ge=0)
    price_currency: str = Field(max_length=MAX_CURRENCY_LENGTH)
    billing_interval: str = Field(default=BILLING_INTERVAL_MONTH, max_length=16)
    entitlements: dict[str, object] = Field(default_factory=dict)


class UpdateResalePlanRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    clear_description: bool = False


class CreateSubscriptionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    platform_plan_key: str | None = None
    resale_plan_id: uuid.UUID | None = None


class ChangeSubscriptionPlanRequest(BaseModel):
    platform_plan_key: str | None = None
    resale_plan_id: uuid.UUID | None = None


class CreateCommercialSubscriptionRequest(BaseModel):
    """The B2B2C commercial subscription request (Step 5) -- `payer
    _tenant_id`/`billing_account_id`/`plan_id` are always explicit,
    independent fields; never inferred from the path's own `tenant_id`
    (`service_tenant_id`), never from each other, and never from tenant
    hierarchy (module docstring). Self-pay is `payer_tenant_id` equal to
    the path's own `tenant_id`; sponsored is `payer_tenant_id` different
    -- the identical request shape, no separate "self-pay" flag or
    endpoint exists because none is needed."""

    payer_tenant_id: uuid.UUID
    billing_account_id: uuid.UUID
    plan_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)


# --- Serialization -------------------------------------------------------------


def _resale_plan_dict(view: ResalePlanView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "key": view.key,
        "name": view.name,
        "description": view.description,
        "price_amount": view.price_amount,
        "price_currency": view.price_currency,
        "billing_interval": view.billing_interval,
        "entitlements": view.entitlements,
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _subscription_dict(view: SubscriptionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "plan_id": str(view.plan_id),
        "plan_key": view.plan_key,
        "resale_plan_id": str(view.resale_plan_id) if view.resale_plan_id else None,
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _plan_dict(view: OwnedPlanView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "owner_tenant_id": str(view.owner_tenant_id),
        "merchant_account_id": str(view.merchant_account_id),
        "key": view.key,
        "name": view.name,
        "entitlements": view.entitlements,
        "visibility": view.visibility,
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _billing_account_dict(view: BillingAccountView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "merchant_tenant_id": str(view.merchant_tenant_id),
        "merchant_account_id": str(view.merchant_account_id),
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _commercial_subscription_dict(view: CommercialSubscriptionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "service_tenant_id": str(view.service_tenant_id),
        "payer_tenant_id": str(view.payer_tenant_id),
        "billing_account_id": str(view.billing_account_id),
        "merchant_account_id": str(view.merchant_account_id),
        "plan_id": str(view.plan_id),
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


# --- Catalog v2: eligible plans (explicit tenant context, Step 5) ---------------


@router.get("/tenants/{tenant_id}/plans")
def list_eligible_plans_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [_plan_dict(v) for v in _call(list_eligible_plans, actor_id, tenant_id)]


# --- BillingAccount (payer's own, Step 5) ---------------------------------------


@router.get("/tenants/{tenant_id}/billing-accounts")
def list_billing_accounts_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [
        _billing_account_dict(v) for v in _call(list_tenant_billing_accounts, actor_id, tenant_id)
    ]


# --- Commercial subscriptions (self-pay and sponsored, Step 5) -----------------


@router.post("/tenants/{tenant_id}/commercial-subscriptions", status_code=status.HTTP_201_CREATED)
def create_commercial_subscription_route(
    tenant_id: uuid.UUID,
    body: CreateCommercialSubscriptionRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _commercial_subscription_dict(
        _call(
            create_commercial_subscription,
            actor_id,
            payer_tenant_id=body.payer_tenant_id,
            service_tenant_id=tenant_id,
            billing_account_id=body.billing_account_id,
            plan_id=body.plan_id,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/commercial-subscriptions/{subscription_id}")
def get_commercial_subscription_route(
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _commercial_subscription_dict(
        _call(get_commercial_subscription, actor_id, tenant_id, subscription_id)
    )


# --- Resale plans (reseller's own catalog) ---------------------------------------


@router.post("/tenants/{tenant_id}/resale-plans", status_code=status.HTTP_201_CREATED)
def create_resale_plan_route(
    tenant_id: uuid.UUID,
    body: CreateResalePlanRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _resale_plan_dict(
        _call(
            create_resale_plan,
            actor_id,
            tenant_id,
            key=body.key,
            name=body.name,
            description=body.description,
            price_amount=body.price_amount,
            price_currency=body.price_currency,
            billing_interval=body.billing_interval,
            entitlements=body.entitlements,
        )
    )


@router.get("/tenants/{tenant_id}/resale-plans")
def list_resale_plans_route(
    tenant_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _resale_plan_dict(v)
        for v in _call(list_resale_plans, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/available-resale-plans")
def list_available_resale_plans_route(
    tenant_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _resale_plan_dict(v)
        for v in _call(list_available_resale_plans, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/resale-plans/{resale_plan_id}")
def get_resale_plan_route(
    tenant_id: uuid.UUID,
    resale_plan_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _resale_plan_dict(_call(get_resale_plan, actor_id, tenant_id, resale_plan_id))


@router.patch("/tenants/{tenant_id}/resale-plans/{resale_plan_id}")
def update_resale_plan_route(
    tenant_id: uuid.UUID,
    resale_plan_id: uuid.UUID,
    body: UpdateResalePlanRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    # `clear_description` disambiguates "omitted" from "explicit null" at
    # the HTTP layer, mirroring `product/websites/routes.py
    # ::update_website_route()`'s own identical `clear_custom_domain` shape.
    if body.clear_description:
        description = None
    elif body.description is not None:
        description = body.description
    else:
        description = ...
    return _resale_plan_dict(
        _call(
            update_resale_plan,
            actor_id,
            tenant_id,
            resale_plan_id,
            name=body.name,
            description=description,
        )
    )


@router.post("/tenants/{tenant_id}/resale-plans/{resale_plan_id}/deactivate")
def deactivate_resale_plan_route(
    tenant_id: uuid.UUID,
    resale_plan_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _resale_plan_dict(_call(deactivate_resale_plan, actor_id, tenant_id, resale_plan_id))


# --- Subscriptions -----------------------------------------------------------------


@router.post("/tenants/{tenant_id}/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription_route(
    tenant_id: uuid.UUID,
    body: CreateSubscriptionRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    if (body.platform_plan_key is None) == (body.resale_plan_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="exactly one of platform_plan_key or resale_plan_id must be supplied.",
        )
    if body.resale_plan_id is not None:
        return _subscription_dict(
            _call(
                create_resale_subscription,
                actor_id,
                tenant_id,
                body.resale_plan_id,
                body.idempotency_key,
            )
        )
    assert body.platform_plan_key is not None
    return _subscription_dict(
        _call(
            create_platform_subscription,
            actor_id,
            tenant_id,
            body.platform_plan_key,
            body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/subscriptions")
def list_subscriptions_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [_subscription_dict(v) for v in _call(list_subscriptions, actor_id, tenant_id)]


@router.get("/tenants/{tenant_id}/subscriptions/{subscription_id}")
def get_subscription_route(
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _subscription_dict(_call(get_subscription, actor_id, tenant_id, subscription_id))


@router.post("/tenants/{tenant_id}/subscriptions/{subscription_id}/change-plan")
def change_subscription_plan_route(
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    body: ChangeSubscriptionPlanRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _subscription_dict(
        _call(
            change_subscription_plan,
            actor_id,
            tenant_id,
            subscription_id,
            platform_plan_key=body.platform_plan_key,
            resale_plan_id=body.resale_plan_id,
        )
    )


@router.post("/tenants/{tenant_id}/subscriptions/{subscription_id}/cancel")
def cancel_subscription_route(
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _subscription_dict(_call(cancel_subscription, actor_id, tenant_id, subscription_id))


# --- Effective entitlements ---------------------------------------------------------


@router.get("/tenants/{tenant_id}/entitlements")
def get_effective_entitlements_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _call(get_effective_entitlements, actor_id, tenant_id)


__all__ = ["router"]
