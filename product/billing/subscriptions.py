"""Subscription lifecycle (docs/ROADMAP.md Phase 13.1/13.3).

**Two subscription sources, one mechanism**
(docs/ADR/0012-resale-billing-ownership-model.md): `create_platform_subscription()`
subscribes `tenant_id` directly to a global `core.billing.Plan` (used
identically by a root "Direct Platform Client" or an "Agency" -- nothing
here distinguishes the two); `create_resale_subscription()` subscribes
`tenant_id` to an ancestor's `ResalePlan`, resolving to that plan's own
`underlying_plan_key` and then delegating to the exact same
`core.billing.subscribe_idempotent()` call. Both converge on the
identical `core.billing.Subscription` row shape -- this module never
introduces a second subscription table.

Every mutating function authorizes via
`product.billing.permissions.require()` against `SUBSCRIPTION_RESOURCE`
at `tenant_id` (the recipient -- `core.rbac.can()`'s own `SUBTREE`
semantics already let an ancestor's administrator manage a descendant's
subscription with zero extra code here, docs/ADR/0012-...'s own
"Plan ownership" section), then delegates to `core.billing`'s own,
already-audited service functions -- this module writes its OWN audit
entry ONLY for the resale-specific linkage `core.billing`'s own generic
`billing.subscription_created` entry does not capture (which
`ResalePlan` was used), never a duplicate of what SaaS-OS already logs
for the underlying `core.billing.Subscription` mutation itself.

**Idempotency**: subscription CREATION (platform or resale) requires a
caller-supplied `idempotency_key` and always calls
`core.billing.subscribe_idempotent()` (P1.11) -- a repeated call with the
same key against the same tenant replays the original result rather than
creating a second real (billable) subscription. Plan-change and
cancellation are not given the same treatment -- both are already
idempotent at the business-outcome level (module docstring's own
reasoning, `docs/ADR/0012-...`).

**Entitlement synchronization is a non-issue by construction**:
`core.billing.get_entitlements()` is a live, uncached read (its own
docstring: "Never cached... always re-evaluates... fresh, against the
live database") -- there is no synchronization mechanism to build, and
none is invented here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.billing import (
    BillingProvider,
    Subscription,
    get_entitlements,
    list_plans,
    subscribe_idempotent,
)
from core.billing import cancel_subscription as billing_cancel_subscription
from core.billing import get_subscription as billing_get_subscription
from core.billing import list_subscriptions as billing_list_subscriptions
from core.billing import upgrade_subscription as billing_upgrade_subscription

from product.billing.errors import BillingValidationError
from product.billing.models import RESALE_PLAN_STATUS_ENABLED
from product.billing.permissions import SUBSCRIPTION_RESOURCE, require
from product.billing.resale_plans import get_resale_plan_for_recipient
from product.foundation.events import Event, publish

RESALE_SUBSCRIPTION_CREATED_EVENT_TYPE = "billing.resale_subscription.created"
RESALE_SUBSCRIPTION_CREATED_EVENT_VERSION = 1

_RESALE_PLAN_KEY_PREFIX = "resale:"


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    plan_id: uuid.UUID
    plan_key: str | None
    resale_plan_id: uuid.UUID | None
    status: str
    provider_subscription_id: str
    created_at: datetime
    updated_at: datetime


def _resolve_plan_key(plan_id: uuid.UUID) -> str | None:
    """`core.billing` exposes no `get_plan_by_id()` -- `Subscription`
    stores only `plan_id` (module docstring: SaaS-OS's own `Plan` schema).
    `list_plans()` is the one published function that can resolve it;
    the global catalog is expected to stay small (platform pricing tiers
    plus one auto-created row per `ResalePlan`), so this linear scan is
    the correct, minimal approach -- never a second, product-maintained
    id->key index."""
    for plan in list_plans():
        if plan.id == plan_id:
            return plan.key
    return None


def _resale_plan_id_from_key(plan_key: str | None) -> uuid.UUID | None:
    if plan_key is None or not plan_key.startswith(_RESALE_PLAN_KEY_PREFIX):
        return None
    try:
        return uuid.UUID(plan_key[len(_RESALE_PLAN_KEY_PREFIX) :])
    except ValueError:
        return None


def _to_view(row: Subscription) -> SubscriptionView:
    plan_key = _resolve_plan_key(row.plan_id)
    return SubscriptionView(
        id=row.id,
        tenant_id=row.tenant_id,
        plan_id=row.plan_id,
        plan_key=plan_key,
        resale_plan_id=_resale_plan_id_from_key(plan_key),
        status=row.status,
        provider_subscription_id=row.provider_subscription_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_platform_subscription(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    platform_plan_key: str,
    idempotency_key: str,
    *,
    provider: BillingProvider | None = None,
) -> SubscriptionView:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="create")
    _is_replay, result = subscribe_idempotent(
        tenant_id,
        platform_plan_key,
        idempotency_key,
        provider=provider,
        actor_user_id=actor_user_id,
    )
    subscription = billing_get_subscription(tenant_id, result.subscription_id)
    return _to_view(subscription)


def create_resale_subscription(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resale_plan_id: uuid.UUID,
    idempotency_key: str,
    *,
    provider: BillingProvider | None = None,
) -> SubscriptionView:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="create")
    resale_plan = get_resale_plan_for_recipient(tenant_id, resale_plan_id)
    if resale_plan.status != RESALE_PLAN_STATUS_ENABLED:
        raise BillingValidationError("that resale plan is not currently available.")

    _is_replay, result = subscribe_idempotent(
        tenant_id,
        resale_plan.underlying_plan_key,
        idempotency_key,
        provider=provider,
        actor_user_id=actor_user_id,
    )

    # Additive to core.billing's own `billing.subscription_created` audit
    # entry (module docstring) -- records the resale-specific linkage that
    # entry's own generic `plan_key` metadata does not name.
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="billing.resale_subscription.created",
        resource_type="billing.subscription",
        resource_id=str(result.subscription_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"resale_plan_id": str(resale_plan_id)},
    )
    publish(
        Event(
            type=RESALE_SUBSCRIPTION_CREATED_EVENT_TYPE,
            version=RESALE_SUBSCRIPTION_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "subscription_id": str(result.subscription_id),
                "resale_plan_id": str(resale_plan_id),
            },
        )
    )
    subscription = billing_get_subscription(tenant_id, result.subscription_id)
    return _to_view(subscription)


def get_subscription(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, subscription_id: uuid.UUID
) -> SubscriptionView:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="read")
    subscription = billing_get_subscription(tenant_id, subscription_id)
    return _to_view(subscription)


def list_subscriptions(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[SubscriptionView]:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="read")
    return [_to_view(row) for row in billing_list_subscriptions(tenant_id)]


def change_subscription_plan(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    *,
    platform_plan_key: str | None = None,
    resale_plan_id: uuid.UUID | None = None,
    provider: BillingProvider | None = None,
) -> SubscriptionView:
    """Exactly one of `platform_plan_key`/`resale_plan_id` must be
    supplied -- the same two-source model `create_platform_subscription()`/
    `create_resale_subscription()` establish, applied to plan changes."""
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="update")
    if (platform_plan_key is None) == (resale_plan_id is None):
        raise BillingValidationError(
            "exactly one of platform_plan_key or resale_plan_id must be supplied."
        )

    if resale_plan_id is not None:
        resale_plan = get_resale_plan_for_recipient(tenant_id, resale_plan_id)
        if resale_plan.status != RESALE_PLAN_STATUS_ENABLED:
            raise BillingValidationError("that resale plan is not currently available.")
        new_plan_key = resale_plan.underlying_plan_key
    else:
        assert platform_plan_key is not None
        new_plan_key = platform_plan_key

    subscription = billing_upgrade_subscription(
        tenant_id,
        subscription_id,
        new_plan_key,
        provider=provider,
        actor_user_id=actor_user_id,
    )
    return _to_view(subscription)


def cancel_subscription(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    *,
    provider: BillingProvider | None = None,
) -> SubscriptionView:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="cancel")
    subscription = billing_cancel_subscription(
        tenant_id, subscription_id, provider=provider, actor_user_id=actor_user_id
    )
    return _to_view(subscription)


def get_effective_entitlements(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, object]:
    require(actor_user_id, tenant_id, resource=SUBSCRIPTION_RESOURCE, action="read")
    return get_entitlements(tenant_id)


__all__ = [
    "RESALE_SUBSCRIPTION_CREATED_EVENT_TYPE",
    "SubscriptionView",
    "cancel_subscription",
    "change_subscription_plan",
    "create_platform_subscription",
    "create_resale_subscription",
    "get_effective_entitlements",
    "get_subscription",
    "list_subscriptions",
]
