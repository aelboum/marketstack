"""Product-defined permissions for `product/automation/` (docs/ROADMAP.md
Phase 10.2). Mirrors `product/telephony/permissions.py`'s own discipline.

**`WORKFLOW_RESOURCE` gates workflow CRUD only, never execution** -- see
`product/automation/errors.py::AutomationAccessDeniedError`'s own
docstring and `docs/ADR/0008-automation-depends-on-crm.md`'s point 2 for
why execution authorization is delegated entirely to the underlying CRM
function each action invokes, using the workflow's own
`created_by_user_id`.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.automation.errors import AutomationAccessDeniedError

WORKFLOW_RESOURCE = "automation.workflow"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise AutomationAccessDeniedError(
            actor_user_id, tenant_id, resource=resource, action=action
        )
