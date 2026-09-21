"""Resale-plan catalog management (docs/ROADMAP.md Phase 13.2).

Every mutating/read function authorizes via
`product.billing.permissions.require()` first, then the actual database
access, then `core.audit_log.record()` for mutations -- metadata carries
only identifiers, never a resale plan's own name/description/price
(mirrors `product/reputation/review_requests.py`'s own bounded/
identifier-only metadata discipline).

**Commercial terms are immutable after creation** -- `update_resale_plan()`
only ever changes display metadata (`name`, `description`), never
`price_amount`/`price_currency`/`billing_interval`/`entitlements`.
Verified directly against `core.billing`'s own published service surface
(`core/billing/service.py`): it exposes `create_plan`/`get_plan`/
`list_plans` only -- no `update_plan()` exists to propagate a changed
`entitlements` dict onto an already-created `core.billing.Plan` row, and
every subscriber's `get_entitlements()` reads that Plan row directly. Half
-supporting an entitlements edit that never actually reaches existing
subscribers would be silently incorrect, not a smaller feature -- so this
module does not offer it. A reseller who wants different commercial terms
creates a new `ResalePlan` (a new `key`, a new underlying
`core.billing.Plan`) and `deactivate_resale_plan()`s the old one; existing
subscribers to the old plan are unaffected until they are migrated by an
explicit `product/billing/subscriptions.py::change_plan()` call, exactly
the same "a plan change is a deliberate, explicit act" shape
`core.billing.upgrade_subscription()` itself already has.

**The resale-tier ceiling check** (`_validate_entitlement_ceiling()`,
docs/ADR/0012-resale-billing-ownership-model.md) runs against
`core.billing.get_entitlements(tenant_id)` -- the reseller's own, live,
hierarchy-aware entitlement read -- at creation time only (entitlements
are immutable thereafter, so there is nothing to re-validate later; if the
reseller's own plan is later downgraded, an already-created `ResalePlan`
is not retroactively invalidated -- documented, not a gap: revoking an
already-sold commercial tier retroactively is a business decision this
phase does not make unilaterally).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.billing import create_plan, get_entitlements
from core.tenancy import get_ancestor_chain
from infra.db import IntegrityError, select, tenant_session_scope

from product.billing.errors import (
    BillingConflictError,
    BillingReferenceNotFoundError,
    BillingValidationError,
    ResaleTierCeilingExceededError,
)
from product.billing.models import (
    BILLING_INTERVAL_MONTH,
    BILLING_INTERVALS,
    MAX_DESCRIPTION_LENGTH,
    MAX_KEY_LENGTH,
    MAX_NAME_LENGTH,
    RESALE_PLAN_STATUS_DISABLED,
    RESALE_PLAN_STATUS_ENABLED,
    ResalePlan,
)
from product.billing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.billing.permissions import RESALE_PLAN_RESOURCE, SUBSCRIPTION_RESOURCE, require
from product.foundation.events import Event, publish

RESALE_PLAN_CREATED_EVENT_TYPE = "billing.resale_plan.created"
RESALE_PLAN_CREATED_EVENT_VERSION = 1
RESALE_PLAN_DEACTIVATED_EVENT_TYPE = "billing.resale_plan.deactivated"
RESALE_PLAN_DEACTIVATED_EVENT_VERSION = 1

_UNDERLYING_PLAN_KEY_PREFIX = "resale"


@dataclass(frozen=True, slots=True)
class ResalePlanView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    key: str
    name: str
    description: str | None
    price_amount: int
    price_currency: str
    billing_interval: str
    entitlements: dict
    status: str
    underlying_plan_key: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _to_view(row: ResalePlan) -> ResalePlanView:
    return ResalePlanView(
        id=row.id,
        tenant_id=row.tenant_id,
        key=row.key,
        name=row.name,
        description=row.description,
        price_amount=row.price_amount,
        price_currency=row.price_currency,
        billing_interval=row.billing_interval,
        entitlements=row.entitlements,
        status=row.status,
        underlying_plan_key=row.underlying_plan_key,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_key(key: str) -> str:
    if not isinstance(key, str) or not key.strip():
        raise BillingValidationError("key must not be empty.")
    if len(key) > MAX_KEY_LENGTH:
        raise BillingValidationError(f"key exceeds {MAX_KEY_LENGTH} characters.")
    return key


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise BillingValidationError("name must not be empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise BillingValidationError(f"name exceeds {MAX_NAME_LENGTH} characters.")
    return name


def _validate_description(description: str | None) -> str | None:
    if description is None:
        return None
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise BillingValidationError(f"description exceeds {MAX_DESCRIPTION_LENGTH} characters.")
    return description


def _validate_price_amount(price_amount: int) -> int:
    if not isinstance(price_amount, int) or isinstance(price_amount, bool) or price_amount < 0:
        raise BillingValidationError("price_amount must be a non-negative integer.")
    return price_amount


def _validate_price_currency(price_currency: str) -> str:
    is_three_letter_code = (
        isinstance(price_currency, str) and len(price_currency) == 3 and price_currency.isalpha()
    )
    if not is_three_letter_code:
        raise BillingValidationError("price_currency must be a 3-letter ISO 4217 code.")
    return price_currency.upper()


def _validate_billing_interval(billing_interval: str) -> str:
    if billing_interval not in BILLING_INTERVALS:
        raise BillingValidationError(f"billing_interval must be one of {BILLING_INTERVALS}.")
    return billing_interval


def _validate_entitlement_ceiling(tenant_id: uuid.UUID, entitlements: dict[str, object]) -> None:
    """The resale-tier ceiling check (module docstring) -- every key in
    `entitlements` must not exceed `tenant_id`'s own, current, live
    entitlement value."""
    ceiling = get_entitlements(tenant_id)
    for key, value in entitlements.items():
        ceiling_value = ceiling.get(key)
        if isinstance(value, bool):
            if value and ceiling_value is not True:
                raise ResaleTierCeilingExceededError(key)
        elif isinstance(value, int | float):
            ceiling_numeric: int | float = 0
            if isinstance(ceiling_value, int | float) and not isinstance(ceiling_value, bool):
                ceiling_numeric = ceiling_value
            if value > ceiling_numeric:
                raise ResaleTierCeilingExceededError(key)
        else:
            raise BillingValidationError(
                f"entitlement {key!r} has an unsupported value type; only bool/int/float allowed."
            )


def create_resale_plan(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    key: str,
    name: str,
    description: str | None = None,
    price_amount: int,
    price_currency: str,
    billing_interval: str = BILLING_INTERVAL_MONTH,
    entitlements: dict[str, object] | None = None,
) -> ResalePlanView:
    require(actor_user_id, tenant_id, resource=RESALE_PLAN_RESOURCE, action="create")
    validated_key = _validate_key(key)
    validated_name = _validate_name(name)
    validated_description = _validate_description(description)
    validated_price_amount = _validate_price_amount(price_amount)
    validated_price_currency = _validate_price_currency(price_currency)
    validated_billing_interval = _validate_billing_interval(billing_interval)
    validated_entitlements = dict(entitlements or {})
    _validate_entitlement_ceiling(tenant_id, validated_entitlements)

    resale_plan_id = uuid.uuid4()
    underlying_plan_key = f"{_UNDERLYING_PLAN_KEY_PREFIX}:{resale_plan_id}"

    # Calls the external (to this table) core.billing catalog first, only
    # persisting this product's own row once that succeeds -- mirrors
    # core.billing.subscribe()'s own "call the external system first"
    # ordering discipline for the identical reason (module docstring's own
    # "orphaned Plan" acceptance covers the narrow failure window between
    # these two steps).
    create_plan(
        underlying_plan_key,
        validated_name,
        entitlements=validated_entitlements,
        provider_price_id=None,
    )

    try:
        with tenant_session_scope(tenant_id) as session:
            session.add(
                ResalePlan(
                    id=resale_plan_id,
                    tenant_id=tenant_id,
                    key=validated_key,
                    name=validated_name,
                    description=validated_description,
                    price_amount=validated_price_amount,
                    price_currency=validated_price_currency,
                    billing_interval=validated_billing_interval,
                    entitlements=validated_entitlements,
                    status=RESALE_PLAN_STATUS_ENABLED,
                    underlying_plan_key=underlying_plan_key,
                    created_by_user_id=actor_user_id,
                )
            )
            session.flush()
    except IntegrityError as exc:
        raise BillingConflictError("key", validated_key) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(ResalePlan, resale_plan_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="billing.resale_plan.created",
        resource_type="billing.resale_plan",
        resource_id=str(resale_plan_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"key": validated_key, "underlying_plan_key": underlying_plan_key},
    )
    publish(
        Event(
            type=RESALE_PLAN_CREATED_EVENT_TYPE,
            version=RESALE_PLAN_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"resale_plan_id": str(resale_plan_id)},
        )
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, resale_plan_id: uuid.UUID) -> ResalePlan:
    row = session.get(ResalePlan, resale_plan_id)
    if row is None or row.tenant_id != tenant_id:
        raise BillingReferenceNotFoundError("resale_plan", resale_plan_id)
    return row


def get_resale_plan(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, resale_plan_id: uuid.UUID
) -> ResalePlanView:
    require(actor_user_id, tenant_id, resource=RESALE_PLAN_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, resale_plan_id)
        session.expunge(row)
    return _to_view(row)


def list_resale_plans(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ResalePlanView]:
    """Lists `tenant_id`'s OWN resale catalog (the reseller's management
    view) -- gated by `RESALE_PLAN_RESOURCE`. Contrast
    `list_available_resale_plans()`, the recipient-facing view."""
    require(actor_user_id, tenant_id, resource=RESALE_PLAN_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(ResalePlan)
                .where(ResalePlan.tenant_id == tenant_id)
                .order_by(ResalePlan.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def list_available_resale_plans(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ResalePlanView]:
    """Lists the ENABLED resale plans `tenant_id` may subscribe to --
    every one defined by an ancestor tenant (`core.tenancy
    .get_ancestor_chain()`, nearest-first), gated by `tenant_id`'s own
    `SUBSCRIPTION_RESOURCE:read` (the recipient's own permission, never
    the reseller's `RESALE_PLAN_RESOURCE`) -- a client does not need any
    authority over its parent's catalog just to see what it may subscribe
    to. Queries each ancestor's own `tenant_session_scope()` individually
    (bounded by `core.tenancy.TenancyConfig.max_hierarchy_depth`, default
    6) rather than opening an unscoped session across tenants -- RLS
    defense-in-depth is never bypassed for tenant-owned data, even for
    this cross-tenant, product-approved read."""
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    views: list[ResalePlanView] = []
    for ancestor_id in get_ancestor_chain(tenant_id):
        with tenant_session_scope(ancestor_id) as session:
            rows = (
                session.execute(
                    select(ResalePlan).where(
                        ResalePlan.tenant_id == ancestor_id,
                        ResalePlan.status == RESALE_PLAN_STATUS_ENABLED,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.expunge(row)
        views.extend(_to_view(row) for row in rows)
    return views[max(offset, 0) : max(offset, 0) + bounded_limit]


def get_resale_plan_for_recipient(
    recipient_tenant_id: uuid.UUID, resale_plan_id: uuid.UUID
) -> ResalePlan:
    """Resolves `resale_plan_id` to a real `ResalePlan` row owned by one of
    `recipient_tenant_id`'s own ancestors -- the shared lookup
    `product/billing/subscriptions.py::create_resale_subscription()`/
    `change_plan()` both use to validate a subscribe/change-plan target
    without ever opening an unscoped cross-tenant session (module
    docstring's own "RLS defense-in-depth is never bypassed" discipline
    on `list_available_resale_plans()`, applied identically here).
    `BillingReferenceNotFoundError` if no ancestor owns a matching row --
    deliberately the same error whether the id is entirely unknown or
    belongs to a tenant outside `recipient_tenant_id`'s own ancestor
    chain (non-enumerating, mirrors `core.billing
    .SubscriptionNotFoundError`'s own identical shape). Returns the ORM
    row (not a view) -- internal to this module and `subscriptions.py`,
    never returned directly from an API route."""
    for ancestor_id in get_ancestor_chain(recipient_tenant_id):
        with tenant_session_scope(ancestor_id) as session:
            row = session.get(ResalePlan, resale_plan_id)
            if row is not None and row.tenant_id == ancestor_id:
                session.expunge(row)
                return row
    raise BillingReferenceNotFoundError("resale_plan", resale_plan_id)


def update_resale_plan(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resale_plan_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = ...,  # type: ignore[assignment] -- sentinel: omitted vs. explicit None
) -> ResalePlanView:
    """Display metadata only (module docstring) -- `...` (Ellipsis) is
    `description`'s own "omitted" sentinel, mirroring
    `product/websites/websites.py::update_website()`'s identical shape."""
    require(actor_user_id, tenant_id, resource=RESALE_PLAN_RESOURCE, action="update")
    validated_name = _validate_name(name) if name is not None else None
    validated_description = _validate_description(description) if description is not ... else ...

    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, resale_plan_id)
        if validated_name is not None:
            row.name = validated_name
        if validated_description is not ...:
            row.description = validated_description
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="billing.resale_plan.updated",
        resource_type="billing.resale_plan",
        resource_id=str(resale_plan_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def deactivate_resale_plan(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, resale_plan_id: uuid.UUID
) -> ResalePlanView:
    """Sets `status='disabled'` -- no longer offered to new subscribers
    (`create_resale_subscription()` checks this); existing subscribers
    against its underlying `core.billing.Plan` are unaffected (module
    docstring). No `reactivate` in this phase -- deferred, since
    re-enabling would need the ceiling re-validated against the
    reseller's potentially-changed own entitlements, a deliberate
    decision this phase does not make speculatively."""
    require(actor_user_id, tenant_id, resource=RESALE_PLAN_RESOURCE, action="deactivate")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, resale_plan_id)
        row.status = RESALE_PLAN_STATUS_DISABLED
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="billing.resale_plan.deactivated",
        resource_type="billing.resale_plan",
        resource_id=str(resale_plan_id),
        outcome=AuditOutcome.SUCCESS,
    )
    publish(
        Event(
            type=RESALE_PLAN_DEACTIVATED_EVENT_TYPE,
            version=RESALE_PLAN_DEACTIVATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"resale_plan_id": str(resale_plan_id)},
        )
    )
    return _to_view(row)


__all__ = [
    "RESALE_PLAN_CREATED_EVENT_TYPE",
    "RESALE_PLAN_DEACTIVATED_EVENT_TYPE",
    "ResalePlanView",
    "create_resale_plan",
    "deactivate_resale_plan",
    "get_resale_plan",
    "get_resale_plan_for_recipient",
    "list_available_resale_plans",
    "list_resale_plans",
    "update_resale_plan",
]
