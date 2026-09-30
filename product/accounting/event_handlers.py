"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own seven `accounting.*` resource
permissions to the newly provisioned role -- the "module needing another
module's capability reacts via the event dispatcher" path
`docs/ARCHITECTURE.md` section 2.2 prescribes for permission-granting
specifically, mirrors `product/reputation/event_handlers.py`'s own
identical subscription. `product.accounting` never imports
`product.agency` directly.

**Higher-risk actions are owner-only**, mirroring
`product/reputation/event_handlers.py`'s own "cancel is owner-only"
precedent, extended by ADR-0014 Decision 13 to Phase 25's own resources:
reversing a *posted* journal entry, closing/reopening a period,
cancelling a *posted* invoice, approving/posting a bill (segregation-of-
duties on outgoing spend, Decision 13's own deliberate asymmetry with
invoice posting), and reversing a payment allocation are all judged the
same higher-risk tier as Reputation's `cancel` and CRM/Websites'
`delete`. `owner`: full lifecycle on all seven resources. `member`:
ordinary day-to-day bookkeeping -- ordinary create/update/void/post/read
actions on every resource, but never `reverse`/`cancel`/`bill.post`/
`reverse_allocation`. `CREDIT_NOTE_RESOURCE` (Phase 15.3) has no
higher-risk action to withhold from `member` at all -- `create`/`void`/
`post`/`read` are granted identically to `owner` and `member`
(`product/accounting/permissions.py`'s own module docstring)."""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.accounting.permissions import (
    ACCOUNT_RESOURCE,
    BILL_RESOURCE,
    CREDIT_NOTE_RESOURCE,
    INVOICE_RESOURCE,
    JOURNAL_RESOURCE,
    PAYMENT_RESOURCE,
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
    (INVOICE_RESOURCE, ("create", "update", "void", "post", "cancel", "read")),
    (BILL_RESOURCE, ("create", "update", "void", "post", "cancel", "read")),
    (PAYMENT_RESOURCE, ("create", "allocate", "reverse_allocation", "read")),
    (CREDIT_NOTE_RESOURCE, ("create", "void", "post", "read")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ACCOUNT_RESOURCE, ("create", "read", "update")),
    (PERIOD_RESOURCE, ("create", "read")),
    (JOURNAL_RESOURCE, ("create", "update", "void", "post", "read")),
    (INVOICE_RESOURCE, ("create", "update", "void", "post", "read")),
    (BILL_RESOURCE, ("create", "update", "void", "read")),
    (PAYMENT_RESOURCE, ("create", "allocate", "read")),
    (CREDIT_NOTE_RESOURCE, ("create", "void", "post", "read")),
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
