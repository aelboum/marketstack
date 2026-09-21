"""Product-owned exceptions for `product/billing/` (docs/ROADMAP.md
Phase 13). Mirrors `product/reputation/errors.py`'s own discipline
exactly. SaaS-OS's own `core.billing` errors (`PlanNotFoundError`,
`SubscriptionNotFoundError`, `EntitlementDeniedError`,
`InvalidBillingHierarchyError`, `InheritedBillingSubscriptionError`,
`BillingProviderError`) are used unchanged wherever they apply -- this
module only adds exceptions genuinely specific to this product's own
resale-plan authorization/integrity checks (docs/ADR/0012-...).
"""

from __future__ import annotations

import uuid


class BillingAccessDeniedError(Exception):
    """Raised by every `product/billing/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/billing/permissions.py
    ::require()`, the one authorization chokepoint every mutating and
    read function here calls first, before any database access."""

    def __init__(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str
    ) -> None:
        self.actor_user_id = actor_user_id
        self.tenant_id = tenant_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for {action!r} on {resource!r} "
            f"in tenant {tenant_id}."
        )


class BillingReferenceNotFoundError(Exception):
    """Raised when a caller-supplied resale-plan id (or a resale plan not
    reachable from the target tenant's own ancestor chain) does not
    resolve to a usable row. Mapped to the same non-enumerating 404 as
    `BillingAccessDeniedError` at the API layer."""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found or not available to this tenant.")


class BillingValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an invalid price/currency/billing interval, an unsupported plan
    source, an invalid lifecycle transition) -- a 400-shaped client error,
    never an authorization or lookup failure."""


class ResaleTierCeilingExceededError(ValueError):
    """Raised when a proposed `ResalePlan.entitlements` value would grant
    a descendant more than the reseller's own current entitlements permit
    (docs/ADR/0012-...'s own "Resale-tier ceiling check" section,
    docs/ROADMAP.md Phase 13.2's own named security consideration: "an
    agency must not be able to define a plan that grants a client more
    platform-level entitlement than the agency's own subscription
    actually has"). Deliberately its own type, distinct from
    `BillingValidationError` -- this is a revenue-integrity rule, not a
    shape problem; mapped to `400` at the API layer, with a message
    naming only the offending key, never the reseller's full entitlement
    set."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"entitlement {key!r} would exceed this tenant's own current plan.")


class BillingConflictError(Exception):
    """Raised for a genuine state conflict this module's own logic
    detects (e.g. a duplicate resale-plan `key` within the same reseller
    tenant) -- the service-layer translation of the real,
    database-enforced `UNIQUE` constraint violation, never a race-prone
    SELECT-then-INSERT check. Mapped to `409` at the API layer."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} {value!r} is already in use.")


__all__ = [
    "BillingAccessDeniedError",
    "BillingConflictError",
    "BillingReferenceNotFoundError",
    "BillingValidationError",
    "ResaleTierCeilingExceededError",
]
