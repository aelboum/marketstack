"""Product-defined permissions for `product/conversations/` (docs/ROADMAP.md
Phase 5). Mirrors `product/crm/permissions.py` exactly -- `conversations.*`
tables have no SaaS-OS-provided authorization of any kind, so every
mutating/read `product/conversations/*.py` service function calls
`core.rbac.can()` against one of these before touching a row (see
`docs/ADR/0002-...`'s Phase 4 addendum, which applies unchanged to this
module: `get_current_actor` at the ingress layer, this module's own
`can()` check as the real authorization boundary).

Deliberately consolidated: messages (including internal notes) and thread
assignment reuse the parent thread's own `update`/`read` permission --
there is no separate `conversations.message` resource.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.conversations.errors import ConversationAccessDeniedError

THREAD_RESOURCE = "conversations.thread"
TEMPLATE_RESOURCE = "conversations.message_template"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Idempotent check-then-grant, mirroring
    `product/crm/permissions.py::grant_to_role()` exactly."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `ConversationAccessDeniedError` unless `actor_user_id` holds
    `(resource, action)` at `tenant_id` -- the one authorization
    chokepoint every `product/conversations/*.py` service function calls
    first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise ConversationAccessDeniedError(
            actor_user_id, tenant_id, resource=resource, action=action
        )
