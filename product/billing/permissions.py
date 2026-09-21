"""Product-defined permissions for `product/billing/` (docs/ROADMAP.md
Phase 13). Mirrors `product/reputation/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`billing.resale_plans` has no SaaS-OS-provided authorization of any kind
(`core.billing.create_plan()` itself performs none either -- it is not a
tenant-scoped concept at all, `docs/ADR/0012-...`'s own "Plan ownership"
section).

**Two resources** -- `RESALE_PLAN_RESOURCE` gates the reseller's own
catalog management (checked against the *reseller* tenant,
`ResalePlan.tenant_id`); `SUBSCRIPTION_RESOURCE` gates subscription
lifecycle operations and the effective-entitlement read (checked against
the *recipient* tenant, `docs/ADR/0012-...`'s own "Three identities" --
these are deliberately never the same resource, since a client that may
read/create its own subscription must not thereby gain any authority over
its parent agency's resale catalog).
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.billing.errors import BillingAccessDeniedError

RESALE_PLAN_RESOURCE = "billing.resale_plan"
SUBSCRIPTION_RESOURCE = "billing.subscription"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/reputation/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.billing.errors.BillingAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/billing/*.py` service function
    calls first, before any database read or write. Unchanged
    `core.rbac.can()` semantics mean a `SUBTREE`-scoped role already
    reaches a descendant `tenant_id` automatically (e.g. an agency owner
    managing a client's subscription) -- no additional hierarchy-walk code
    is needed here."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise BillingAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)


__all__ = ["RESALE_PLAN_RESOURCE", "SUBSCRIPTION_RESOURCE", "grant_to_role", "require"]
