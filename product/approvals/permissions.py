"""Product-defined permissions for `product/approvals/` (docs/ROADMAP.md
Phase 29). Mirrors `product/appointments/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`control_plane.approval_requests` has no product-facing authorization of
its own (see `product/approvals/__init__.py`'s own module docstring for
why that gate belongs here, not in SaaS-OS).

**One resource, `APPROVAL_RESOURCE`** -- an approval request has no
sub-entity of its own. Three actions: `read` (list/view a tenant's own
approval requests), `decide` (approve or reject a pending one -- the same
action for both, since both are equally a "human decision" and neither is
riskier than the other to gate), `execute` (actually invoke the
underlying tool once approved -- checked separately from `decide` because
"I approved this" and "I am the one who triggers it running" are
deliberately allowed to be different moments/different people, mirroring
`control_plane.approvals.execute_approved()`'s own separate step)."""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.approvals.errors import ApprovalAccessDeniedError

APPROVAL_RESOURCE = "approvals.approval"


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
    """Raise `product.approvals.errors.ApprovalAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/approvals/service.py`
    function calls first, before any `control_plane.approvals` call."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise ApprovalAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)


__all__ = ["APPROVAL_RESOURCE", "grant_to_role", "require"]
