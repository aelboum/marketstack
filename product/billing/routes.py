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

**Global platform-plan catalog read**: `GET /plans` calls `core.billing
.list_plans()` directly, with no `product.billing.permissions.require()`
call -- the global plan catalog is not tenant-owned data (`docs/ADR
/0012-...`'s own "Plan ownership" section; mirrors `core.feature_flags`'
identical global-catalog posture), so any authenticated actor may read it.
Plan *creation* is deliberately not exposed here at all (same section).

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
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import forbidden, not_found, quota_exceeded, service_unavailable
from core.billing import (
    BillingProviderError,
    DuplicatePlanKeyError,
    EntitlementDeniedError,
    InheritedBillingSubscriptionError,
    InvalidBillingHierarchyError,
    InvalidPlanKeyError,
    PlanNotFoundError,
    SubscriptionNotFoundError,
    list_plans,
)
from core.usage import QuotaExceededError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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
)
_CONFLICT_ERRORS: tuple[type[Exception], ...] = (
    BillingConflictError,
    DuplicatePlanKeyError,
    InheritedBillingSubscriptionError,
    InvalidBillingHierarchyError,
)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _CONFLICT_ERRORS:
        raise _conflict(
            "That billing operation conflicts with the tenant's current state."
        ) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except BillingProviderError:
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


# --- Global platform plan catalog (read-only) ------------------------------------


@router.get("/plans")
def list_platform_plans_route(
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    del actor_id  # authentication only -- see module docstring
    return [
        {"key": plan.key, "name": plan.name, "entitlements": plan.entitlements}
        for plan in list_plans()
    ]


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
