"""Product-defined permissions for `product/ai/` (docs/ROADMAP.md Phase
9.4). Mirrors `product/telephony/permissions.py`'s own discipline exactly.

**This gates AI *policy administration*, never AI execution.** Execution
authorization stays entirely `control_plane`'s -- Tool Authorization,
autonomy tier, and Data Authorization are all enforced inside
`invoke_tool()`/`authorize_data_access()` and are never re-implemented,
re-checked, or short-circuited here (docs/ROADMAP.md Phase 9's own "do
not create Product-local equivalents of SaaS-OS AI authorization"
requirement, unchanged by this phase). The one genuinely new thing Phase
9.4 introduces is a Product-owned *table* -- `ai.tenant_policies` -- and
a Product-owned table needs a Product-owned RBAC gate, exactly as every
other product module's own `permissions.py` provides for its own tables.

Deliberately one resource with `read`/`manage`, not a CRUD quartet:
reading a tenant's AI posture and changing it are the only two things
anyone does to this single-row-per-tenant table, and `manage` covers
create/update/disable uniformly (there is no separate "delete a policy"
concept -- disabling is `enabled=False`, which denies exactly as an
absent row does).
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.ai.errors import AIAccessDeniedError

AI_POLICY_RESOURCE = "ai.policy"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/telephony/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.ai.errors.AIAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every policy read/write in
    `product/ai/policy.py` calls first, before any database access."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise AIAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)


__all__ = ["AI_POLICY_RESOURCE", "grant_to_role", "require"]
