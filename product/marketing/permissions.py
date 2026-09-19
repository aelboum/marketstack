"""Product-defined permissions for `product/marketing/` (docs/ROADMAP.md
Phase 6).

Unlike `product/agency/roles.py`'s Core-owned permission pairs, every
permission here is this product's own invention -- `marketing.*` tables
have no SaaS-OS-provided authorization of any kind, so nothing else gates
them. Every mutating and read `product/marketing/*.py` service function
calls `core.rbac.can()` against one of these before touching a
`marketing.*` row (see `docs/ADR/0002-...`'s Phase 4 addendum for why
this is mandatory, not a style choice -- the identical reasoning applies
here: `core.tenancy`/`core.rbac` have no built-in concept of a campaign
or a suppression record).

Deliberately consolidated, not one resource per sub-entity: recipients
are read/mutated via the parent campaign's own permission -- there is no
separate `marketing.campaign_recipient` resource.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.marketing.errors import MarketingAccessDeniedError

CAMPAIGN_RESOURCE = "marketing.campaign"
SUPPRESSION_RESOURCE = "marketing.suppression"
FORM_RESOURCE = "marketing.form"
TEMPLATE_RESOURCE = "marketing.template"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirroring
    `product/crm/permissions.py::grant_to_role()`'s own check-then-grant
    discipline (`core.rbac.grant_permission()` raises on a duplicate
    grant)."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.marketing.errors.MarketingAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/marketing/*.py` service
    function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise MarketingAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)
