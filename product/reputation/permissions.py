"""Product-defined permissions for `product/reputation/` (docs/ROADMAP.md
Phase 12). Mirrors `product/websites/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`reputation.*` tables have no SaaS-OS-provided authorization of any kind.

**Two resources, not one** -- `REVIEW_REQUEST_RESOURCE` covers
`ReviewRequest` only; `REVIEW_RESOURCE` covers both `Review` and
`ReviewResponse` (a response has no independent existence or access
boundary apart from the review it responds to, the same consolidation
`product/websites/permissions.py`'s own module docstring already applies
to `Page` under `Website`). A request and a review are independent
concepts with independent lifecycles -- a review can exist with no
request behind it at all (recorded manually, or in a future provider
sync) -- so, unlike Page/Website, they are not the same resource.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.reputation.errors import ReputationAccessDeniedError

REVIEW_REQUEST_RESOURCE = "reputation.review_request"
REVIEW_RESOURCE = "reputation.review"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/websites/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.reputation.errors.ReputationAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/reputation/*.py` service
    function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise ReputationAccessDeniedError(
            actor_user_id, tenant_id, resource=resource, action=action
        )


__all__ = ["REVIEW_REQUEST_RESOURCE", "REVIEW_RESOURCE", "grant_to_role", "require"]
