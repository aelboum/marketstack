"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own appointments permissions to the
newly provisioned role -- the "module needing another module's
capability reacts via the event dispatcher" path `docs/ARCHITECTURE.md`
section 2.2 prescribes for permission-granting specifically (this is
separate from, and unrelated to, `docs/ADR/0005-marketing-and-
appointments-depend-on-crm.md`'s CRM-read/write exception -- `product
.appointments` still never imports `product.agency` directly, the same
rule `product/crm/event_handlers.py`/`product/marketing/event_handlers.py`
already follow).

**Subscribed at import time, module level** -- see `product/crm
/event_handlers.py`'s own docstring for the full reasoning (this module
is registered the identical way, from `product/api/main.py`).

The `owner` role is granted full CRUD on both `appointments.calendar` and
`appointments.appointment` -- an agency owner manages its own and its
clients' appointments completely. The `member` role (a client's own
baseline role) is granted `create`/`read`/`update` on both (deliberately
NOT `delete`, the same reasoning `product/crm/event_handlers.py`/
`product/marketing/event_handlers.py` already apply) -- cancelling an
appointment is a `status` update via the `update` action
(`product/appointments/booking.py::staff_cancel_appointment()`), not a
`delete`, so a member can still cancel.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.appointments.permissions import APPOINTMENT_RESOURCE, CALENDAR_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CALENDAR_RESOURCE, ("create", "read", "update", "delete")),
    (APPOINTMENT_RESOURCE, ("create", "read", "update", "delete")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CALENDAR_RESOURCE, ("create", "read", "update")),
    (APPOINTMENT_RESOURCE, ("create", "read", "update")),
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
