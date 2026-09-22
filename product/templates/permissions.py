"""Product-defined permissions for `product/templates/` (docs/ROADMAP.md
Phase 14). Mirrors `product/reputation/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`templates.snapshots` has no SaaS-OS-provided authorization of any kind.

**One resource, `SNAPSHOT_RESOURCE`** -- a snapshot has no sub-entity of
its own (unlike Websites' `Page`/Reputation's `ReviewResponse`) to warrant
a second resource. Three actions: `create` (capture a new snapshot from a
tenant), `read` (view/list a tenant's own snapshots -- also the
permission checked on the *source* tenant when applying one elsewhere),
`apply` (create configuration in a tenant from a snapshot -- checked on
the *target* tenant, `docs/ADR/0013-...`'s own "Plan ownership"-shaped
identity separation, mirroring `docs/ADR/0012-...`'s own recipient/
administrator distinction). No `update`/`delete` action exists --
`product/templates/snapshots.py` offers neither.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.templates.errors import TemplatesAccessDeniedError

SNAPSHOT_RESOURCE = "templates.snapshot"


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
    """Raise `product.templates.errors.TemplatesAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/templates/*.py` service
    function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise TemplatesAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)


__all__ = ["SNAPSHOT_RESOURCE", "grant_to_role", "require"]
