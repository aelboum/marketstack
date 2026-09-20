"""Reacts to `agency.role_provisioned` to grant this module's own
`automation.workflow` (10.2) and `automation.durable_workflow` (Phase
10.3) permissions to the newly provisioned role -- mirrors every other
module's identical `event_handlers.py`. `product.automation` never
imports `product.agency` directly.

`owner`: full CRUD plus `execute`/`cancel`/`signal` (durable-run
control). `member`: create/read/update plus `execute`/`cancel`/`signal`,
never `delete` (same reasoning every other module already applies) --
`execute`/`cancel`/`signal` are deliberately granted to `member` too
(not owner-only): this phase's own security model is that every
*business action* a run performs re-authorizes independently at
execution time against the run's own creator, never against whoever
merely started/cancelled/signalled it -- see
`product/automation/durable/runs.py`'s own module docstring.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.automation.durable.permissions import DURABLE_WORKFLOW_RESOURCE
from product.automation.permissions import WORKFLOW_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WORKFLOW_RESOURCE, ("create", "read", "update", "delete")),
    (
        DURABLE_WORKFLOW_RESOURCE,
        ("create", "read", "update", "delete", "execute", "cancel", "signal"),
    ),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WORKFLOW_RESOURCE, ("create", "read", "update")),
    (DURABLE_WORKFLOW_RESOURCE, ("create", "read", "update", "execute", "cancel", "signal")),
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
