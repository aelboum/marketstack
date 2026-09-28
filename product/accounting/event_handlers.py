"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own `accounting.account`/
`accounting.period`/`accounting.journal` permissions to the newly
provisioned role -- the "module needing another module's capability
reacts via the event dispatcher" path `docs/ARCHITECTURE.md` section 2.2
prescribes for permission-granting specifically, mirrors
`product/reputation/event_handlers.py`'s own identical subscription.
`product.accounting` never imports `product.agency` directly.

**Higher-risk actions are owner-only**, mirroring
`product/reputation/event_handlers.py`'s own "cancel is owner-only"
precedent: reversing a *posted* journal entry (a correction that, unlike
voiding a draft, leaves a permanent, visible trace against real financial
history) and closing/reopening a period (which changes what the rest of
the tenant can post against) are both judged the same higher-risk tier as
Reputation's `cancel` and CRM/Websites' `delete`. `owner`: full lifecycle
on all three resources, including `reverse` (journal) and `manage`
(period). `member`: ordinary day-to-day bookkeeping -- create/read/update
accounts, create/read periods, create/update/void/post journal entries --
never `reverse` a posted entry, never `manage` a period's open/closed
state.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.accounting.permissions import (
    ACCOUNT_RESOURCE,
    JOURNAL_RESOURCE,
    PERIOD_RESOURCE,
    grant_to_role,
)
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ACCOUNT_RESOURCE, ("create", "read", "update")),
    (PERIOD_RESOURCE, ("create", "read", "manage")),
    (JOURNAL_RESOURCE, ("create", "update", "void", "post", "reverse", "read")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ACCOUNT_RESOURCE, ("create", "read", "update")),
    (PERIOD_RESOURCE, ("create", "read")),
    (JOURNAL_RESOURCE, ("create", "update", "void", "post", "read")),
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
