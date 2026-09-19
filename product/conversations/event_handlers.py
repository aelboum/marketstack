"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own conversations permissions to the
newly provisioned role -- mirrors `product/crm/event_handlers.py` exactly,
the same "module needing another module's capability reacts via the
event dispatcher" path (`docs/ARCHITECTURE.md` section 2.2) required for
`product.crm`, since `product.conversations` and `product.agency` must
never import each other directly either (the independence contract).

**Subscribed at import time, module level** -- see
`product/crm/event_handlers.py`'s own docstring for the full reasoning
(the handler must be registered before `product.agency.roles`'s own code
publishes, which in this single-process deployment means before any
request is served). `product/api/main.py` imports this module explicitly
for its registration side effect, the same way it already does for
`product.crm.event_handlers`.

The `owner` role is granted full CRUD on both resources -- an agency
owner manages its own and its clients' conversations completely. The
`member` role is granted `create`/`read`/`update` on threads (not
`delete` -- the identical judgment call `product/crm/event_handlers.py`
already made for CRM records: a baseline client member should not be
able to permanently remove conversation history by default) and
`read`-only on templates (creating reusable templates is treated as an
owner-level configuration action, the same category `product/crm
/event_handlers.py` already puts custom-field/tag definitions in --
revisit if a later phase needs client-configurable templates).
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.conversations.permissions import TEMPLATE_RESOURCE, THREAD_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (THREAD_RESOURCE, ("create", "read", "update", "delete")),
    (TEMPLATE_RESOURCE, ("create", "read", "update", "delete")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (THREAD_RESOURCE, ("create", "read", "update")),
    (TEMPLATE_RESOURCE, ("read",)),
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
