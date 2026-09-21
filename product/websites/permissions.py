"""Product-defined permissions for `product/websites/` (docs/ROADMAP.md
Phase 11.1). Mirrors `product/appointments/permissions.py`'s own
discipline exactly -- every permission here is this product's own
invention; `websites.*` tables have no SaaS-OS-provided authorization of
any kind.

**One consolidated resource, `WEBSITE_RESOURCE`, covers both `Website`
and `Page`** -- the same consolidation principle
`product/crm/permissions.py`'s own module docstring establishes for
tasks/notes ("gated by the SAME permission as... the entity they attach
to -- there is no separate `crm.task`/`crm.note` resource"), applied here
because a page has no independent existence or access boundary apart
from the website that owns it; splitting the two would add a permission
axis nothing in the roadmap asks for.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.websites.errors import WebsiteAccessDeniedError

WEBSITE_RESOURCE = "websites.website"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/appointments/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.websites.errors.WebsiteAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/websites/*.py` service
    function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise WebsiteAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)


__all__ = ["WEBSITE_RESOURCE", "grant_to_role", "require"]
