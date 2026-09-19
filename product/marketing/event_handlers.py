"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own marketing permissions to the
newly provisioned role -- the "module needing another module's
capability reacts via the event dispatcher" path `docs/ARCHITECTURE.md`
section 2.2 prescribes for permission-granting specifically (this is
separate from, and unrelated to, `docs/ADR/0005-marketing-depends-on-crm
.md`'s CRM-read exception -- `product.marketing` still never imports
`product.agency` directly, the same rule `product/crm/event_handlers.py`
already follows).

**Subscribed at import time, module level** -- see `product/crm
/event_handlers.py`'s own docstring for the full reasoning (this module
is registered the identical way, from `product/api/main.py`).

The `owner` role is granted full CRUD on `marketing.campaign` and
`marketing.suppression` -- an agency owner manages its own and its
clients' marketing completely. The `member` role (a client's own
baseline role) is granted `create`/`read`/`update` on campaigns
(deliberately NOT `delete`, the same reasoning `product/crm
/event_handlers.py` already applies) and `create`/`read` (NOT `delete`)
on suppressions -- a member can record a manual unsubscribe, but deleting
a suppression effectively re-subscribes a contact, a more consequential,
owner-level action (see `product/marketing/suppressions.py
::delete_suppression()`'s own docstring for the identical reasoning
stated at the point of use).
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.foundation.events import Event, subscribe
from product.marketing.permissions import (
    CAMPAIGN_RESOURCE,
    FORM_RESOURCE,
    SUPPRESSION_RESOURCE,
    TEMPLATE_RESOURCE,
    grant_to_role,
)

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CAMPAIGN_RESOURCE, ("create", "read", "update", "delete")),
    (SUPPRESSION_RESOURCE, ("create", "read", "delete")),
    (FORM_RESOURCE, ("create", "read", "update", "delete")),
    (TEMPLATE_RESOURCE, ("create", "read", "update", "delete")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CAMPAIGN_RESOURCE, ("create", "read", "update")),
    (SUPPRESSION_RESOURCE, ("create", "read")),
    (FORM_RESOURCE, ("create", "read", "update")),
    (TEMPLATE_RESOURCE, ("create", "read", "update")),
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
