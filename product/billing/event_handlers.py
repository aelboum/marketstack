"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own `billing.resale_plan`/
`billing.subscription` permissions to the newly provisioned role -- the
"module needing another module's capability reacts via the event
dispatcher" path `docs/ARCHITECTURE.md` section 2.2 prescribes for
permission-granting specifically. `product.billing` never imports
`product.agency` directly, the same rule every other module's own
`event_handlers.py` already follows.

**Role name is generic on purpose**: `product/agency/roles.py` provisions
`"owner"`/`"member"` for every tenant this product creates (agencies and
their clients alike, `docs/ADR/0012-...`'s own "Direct Platform Client and
Agency are the same structural case" reasoning) -- so this handler grants
identically to both an agency's own root role and a client's own role,
with no special-casing.

`owner`: full control over its own tenant's resale catalog (`create`,
`read`, `update`, `deactivate`) plus full subscription lifecycle
(`create`, `read`, `update`, `cancel`). `member`: `read`-only on the
resale catalog (viewing tiers, never defining pricing -- a
revenue-critical decision reserved for `owner`, mirroring
`product/reputation/event_handlers.py`'s own "cancel is owner-only"
precedent) plus `create`/`read`/`update` on subscriptions, never
`cancel`.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.billing.permissions import RESALE_PLAN_RESOURCE, SUBSCRIPTION_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (RESALE_PLAN_RESOURCE, ("create", "read", "update", "deactivate")),
    (SUBSCRIPTION_RESOURCE, ("create", "read", "update", "cancel")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (RESALE_PLAN_RESOURCE, ("read",)),
    (SUBSCRIPTION_RESOURCE, ("create", "read", "update")),
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
