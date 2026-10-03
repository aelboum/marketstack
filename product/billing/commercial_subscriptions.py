"""B2B2C sponsored subscriptions (docs/ROADMAP.md Phase 15, Step 3) --
the Marketstack service-level entry point over the frozen SaaS-OS
commercial subscription path, `core.billing.commercial.create_subscription()`.

**Foundation only, built on Step 2's commercial-party provisioning**
(`product/billing/parties.py`). This module is the first Marketstack
code to call `core.billing.commercial.create_subscription()` at all --
`product/billing/subscriptions.py`'s existing self-pay/resale path
(`create_platform_subscription()`/`create_resale_subscription()`) still
calls only the legacy `core.billing.subscribe_idempotent()`, unchanged
by this module (see "Legacy path" below). Deliberately NOT implemented
here: Catalog v2 migration of any existing `ResalePlan`, a `PlanOffer`,
any new public API route/field, provider webhooks, Stripe Connect, or
provider onboarding -- all later, separately-scoped phases. The one
Catalog v2 primitive this module genuinely needs (a real, adopted,
active-merchant plan to subscribe to) has no Marketstack production
code that creates one; `tests/billing/test_commercial_subscriptions_integration.py`
builds its own test-only plan directly via `core.billing.catalog
.create_owned_plan()`, exactly mirroring how the frozen SaaS-OS's own
test suite does the identical thing for the identical reason.

**Three explicit parties, never conflated** (ADR-0029, verified directly
against the frozen SHA in `core/billing/commercial.py`'s own module
docstring):

    service tenant  -- `service_tenant_id`: receives the subscription and
                        its entitlements. `core.billing.Subscription
                        .tenant_id`.
    payer            -- `(payer_tenant_id, billing_account_id)`: the
                        `BillingAccount` that is charged. Self-pay:
                        `payer_tenant_id == service_tenant_id`. Sponsored:
                        they differ. Never inferred from each other, never
                        inferred from tenant hierarchy or `SUBTREE` reach
                        -- both are always literal caller-supplied ids,
                        exactly as `core.billing.commercial
                        .create_subscription()` itself requires and
                        independently re-verifies (the billing account is
                        read under the payer's own RLS scope; a caller
                        cannot "supply" one it does not own).
    merchant/payee   -- the plan's own merchant, which must be the
                        billing account's own merchant (`core.billing`'s
                        own composite-foreign-key-enforced invariant,
                        re-checked by `evaluate_plan_eligibility()`).

**Dual authorization, both through the SAME `core.rbac.can()` chokepoint
`core.billing.commercial.create_subscription()` itself uses internally**
(`product/billing/permissions.py::require()`, called here *first*,
before SaaS-OS is ever reached -- the same "product authorizes, then
delegates to an already-audited SaaS-OS function" discipline
`product/billing/resale_plans.py::create_resale_plan()` already
established):

    require(actor_user_id, payer_tenant_id,   resource=BILLING_ACCOUNT_RESOURCE,   action="charge")
    require(actor_user_id, service_tenant_id, resource=SUBSCRIPTION_RESOURCE,      action="create")

Both resource strings are, byte for byte, the frozen contract's own
`core.billing.authorization.BILLING_ACCOUNT`/`BILLING_SUBSCRIPTION`
(`product/billing/permissions.py`'s own module docstring explains why
this is not a coincidence) -- so a denial here and a denial inside
`create_subscription()`'s own internal re-check are never reachable
independently of each other; they read the exact same permission rows.
This product-level pre-check exists for the same two reasons
`product/billing/*.py` already pre-checks everywhere else: a fast,
non-enumerating `BillingAccessDeniedError` before any SaaS-OS call, and
this product's own documented authorization boundary, not an assumed one.

**Hierarchy is never authorization.** Nothing in this module, or in
`core.billing.commercial.create_subscription()`, ever asks "is
`service_tenant_id` a descendant of `payer_tenant_id`." An agency's
`SUBTREE`-scoped role (`product/agency/provisioning.py
::provision_agency()`) is what *structurally* lets an agency owner's
`billing.subscription:create` grant (at the agency's own tenant) also
satisfy the service-tenant check for a client it has authority over --
but that is `core.rbac.can()`'s own, already-audited `SUBTREE` semantics
being invoked normally through the real check, never a hierarchy walk
this module performs instead of it. The payer check is never satisfied
by hierarchy at all: `billing.account:charge` only ever reaches the
tenants a role is actually assigned over (self or `SUBTREE`-descendants
of *that role's own tenant*) -- an unrelated tenant, or a tenant on a
different branch of the hierarchy, is never reachable, with or without
`SUBTREE`, because no role assignment connects them.

**Legacy path.** `product/billing/subscriptions.py::create_platform_subscription()`/
`create_resale_subscription()`/`change_subscription_plan()`/
`cancel_subscription()` are completely unmodified by this module -- they
still call `core.billing.subscribe_idempotent()`/`upgrade_subscription()`/
`cancel_subscription()` exactly as before. This module adds a second,
independent creation path; it does not route anything through, wrap, or
otherwise touch the legacy one. `create_commercial_subscription()` below
is the only new entry point, and it never calls `subscribe_idempotent()`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.authority import UserCaller
from core.billing import BillingProvider, Subscription
from core.billing import create_subscription as _create_commercial_subscription
from core.billing import get_subscription as _billing_get_subscription

from product.billing.permissions import (
    BILLING_ACCOUNT_RESOURCE,
    SUBSCRIPTION_RESOURCE,
    require,
)

#: `core.idempotency`'s own operation-name validation (frozen
#: `core/idempotency/service.py::_validate_operation()`) is a fixed
#: string this module names once -- never caller-supplied, never
#: collides with `core.billing.commercial`'s own internal
#: `"billing.subscription.create"` (a different tenant-scoped namespace:
#: `core.idempotency` reservations are keyed by
#: `(tenant_id, operation, idempotency_key)`, and `operation` there is
#: SaaS-OS's own fixed constant, not caller-visible or overridable from
#: here).


@dataclass(frozen=True, slots=True)
class CommercialSubscriptionView:
    """The explicit parties, named separately, never conflated (module
    docstring) -- unlike `product/billing/subscriptions.py::SubscriptionView`,
    which never exposes payer/merchant at all (every subscription it
    returns is still legacy-created, self-pay only)."""

    id: uuid.UUID
    service_tenant_id: uuid.UUID
    payer_tenant_id: uuid.UUID
    billing_account_id: uuid.UUID
    merchant_account_id: uuid.UUID
    plan_id: uuid.UUID
    status: str
    provider_subscription_id: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: Subscription) -> CommercialSubscriptionView:
    # Every field below is non-NULL for a verified commercial row (module
    # docstring; `core/billing/models.py::Subscription`'s own
    # `ck_billing_subscriptions_payer_pair`/`ck_billing_subscriptions_merchant_pair`
    # check constraints guarantee payer/billing-account/merchant are all
    # set together or none at all) -- `create_subscription()` always
    # writes a `verified` row (`core/billing/commercial.py::_insert_pending()`),
    # so a row reaching here always has them.
    assert row.payer_tenant_id is not None
    assert row.billing_account_id is not None
    assert row.merchant_account_id is not None
    return CommercialSubscriptionView(
        id=row.id,
        service_tenant_id=row.tenant_id,
        payer_tenant_id=row.payer_tenant_id,
        billing_account_id=row.billing_account_id,
        merchant_account_id=row.merchant_account_id,
        plan_id=row.plan_id,
        status=row.status,
        provider_subscription_id=row.provider_subscription_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_commercial_subscription(
    actor_user_id: uuid.UUID,
    *,
    payer_tenant_id: uuid.UUID,
    service_tenant_id: uuid.UUID,
    billing_account_id: uuid.UUID,
    plan_id: uuid.UUID,
    idempotency_key: str,
    provider: BillingProvider | None = None,
) -> CommercialSubscriptionView:
    """Create a Catalog v2 commercial subscription: `service_tenant_id`
    receives the entitlements, `payer_tenant_id`'s `billing_account_id`
    is charged -- self-pay when they are equal, sponsored when they are
    not (module docstring). Dual-authorizes `actor_user_id` against both
    tenants *before* calling `core.billing.commercial.create_subscription()`,
    which re-authorizes and re-verifies everything again, independently,
    inside its own transaction -- this function adds no authority
    `create_subscription()` does not also check for itself; it only adds
    a product-level, non-enumerating denial before SaaS-OS is reached.

    Idempotent exactly as `core.billing.commercial.create_subscription()`
    itself is (module docstring; `core/idempotency`'s own
    `(tenant_id, operation, idempotency_key)` reservation, fingerprinted
    by `{plan_id, payer_tenant_id, billing_account_id}`): a repeated call
    with the same `idempotency_key` for the same `service_tenant_id`
    replays the original result; the same key with a different
    `payer_tenant_id`/`billing_account_id`/`plan_id` raises
    `core.idempotency.IdempotencyKeyReusedError` -- it can never silently
    reuse another request's subscription. A different `service_tenant_id`
    is an entirely separate reservation (keyed by that tenant), never a
    collision with this one."""
    require(actor_user_id, payer_tenant_id, resource=BILLING_ACCOUNT_RESOURCE, action="charge")
    require(actor_user_id, service_tenant_id, resource=SUBSCRIPTION_RESOURCE, action="create")
    _is_replay, result = _create_commercial_subscription(
        UserCaller(actor_user_id),
        service_tenant_id=service_tenant_id,
        payer_tenant_id=payer_tenant_id,
        billing_account_id=billing_account_id,
        plan_id=plan_id,
        idempotency_key=idempotency_key,
        provider=provider,
    )
    subscription = _billing_get_subscription(service_tenant_id, result.subscription_id)
    return _to_view(subscription)


def get_commercial_subscription(
    actor_user_id: uuid.UUID, service_tenant_id: uuid.UUID, subscription_id: uuid.UUID
) -> CommercialSubscriptionView:
    """Read back one commercial subscription -- authorized against the
    service tenant only (`billing.subscription:read`, the same action
    `product/billing/subscriptions.py::get_subscription()` already uses
    for the legacy path): reading a subscription's own record is a
    service-tenant concern, never a payer one (the payer's own durable
    view is its payer projection, a later phase, module docstring of
    `core/billing/commercial.py`)."""
    require(actor_user_id, service_tenant_id, resource=SUBSCRIPTION_RESOURCE, action="read")
    subscription = _billing_get_subscription(service_tenant_id, subscription_id)
    return _to_view(subscription)


__all__ = [
    "CommercialSubscriptionView",
    "create_commercial_subscription",
    "get_commercial_subscription",
]
