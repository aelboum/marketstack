"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own `websites.website` permissions to
the newly provisioned role -- the "module needing another module's
capability reacts via the event dispatcher" path `docs/ARCHITECTURE.md`
section 2.2 prescribes for permission-granting specifically.
`product.websites` never imports `product.agency` directly, the same
rule every other module's own `event_handlers.py` already follows.

`owner`: full CRUD. `member`: create/read/update, never delete (same
reasoning every other module already applies) -- websites are not
identified as a higher-risk resource than CRM/appointments/telephony
data, so no owner-only restriction beyond the existing delete-only split.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.foundation.events import Event, subscribe
from product.websites.permissions import WEBSITE_RESOURCE, grant_to_role

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WEBSITE_RESOURCE, ("create", "read", "update", "delete")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WEBSITE_RESOURCE, ("create", "read", "update")),
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
