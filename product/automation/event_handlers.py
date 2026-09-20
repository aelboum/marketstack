"""Reacts to `agency.role_provisioned` to grant this module's own
`automation.workflow` permissions to the newly provisioned role -- mirrors
every other module's identical `event_handlers.py`. `product.automation`
never imports `product.agency` directly.

`owner`: full CRUD. `member`: create/read/update, never delete (same
reasoning every other module already applies).
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.automation.permissions import WORKFLOW_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WORKFLOW_RESOURCE, ("create", "read", "update", "delete")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WORKFLOW_RESOURCE, ("create", "read", "update")),
)


def _handle_agency_role_provisioned(event: Event) -> None:
    role_name = event.payload.get("role_name")
    if role_name not in (_OWNER_ROLE_NAME, _MEMBER_ROLE_NAME):
        return
    tenant_id = uuid.UUID(event.tenant_id)
    role_id = uuid.UUID(str(event.payload["role_id"]))
    role = get_role(tenant_id, role_id)
    grants = _OWNER_GRANTS if role_name == _OWNER_ROLE_NAME else _MEMBER_GRANTS
    for resource, actions in grants:
        grant_to_role(tenant_id, role, resource=resource, actions=actions)


subscribe("agency.role_provisioned", _handle_agency_role_provisioned)
