"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own `approvals.approval` permissions
to the newly provisioned role -- the same pattern every other module's
own `event_handlers.py` already follows. `product.approvals` never
imports `product.agency` directly.

`owner`: full lifecycle (`read`, `decide`, `execute`). `member`: `read`
only -- deciding or executing a tier>=1 action is exactly the kind of
higher-risk-than-ordinary-CRUD action
`product/reputation/event_handlers.py`'s own module docstring reserves
for the `owner` tier alone (there, `cancel`/`deactivate`-shaped actions;
here, approving or actually running a proposed autonomous action)."""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.approvals.permissions import APPROVAL_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (APPROVAL_RESOURCE, ("read", "decide", "execute")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = ((APPROVAL_RESOURCE, ("read",)),)


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
