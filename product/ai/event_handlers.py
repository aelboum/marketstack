"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own AI-policy permissions to the newly
provisioned role -- the "module needing another module's capability
reacts via the event dispatcher" path `docs/ARCHITECTURE.md` section 2.2
prescribes for permission-granting specifically. `product.ai` never
imports `product.agency` directly, the same rule every other module's own
`event_handlers.py` already follows.

**`ai.policy`/`manage` is granted to `owner` only, never `member`**
(docs/ROADMAP.md Phase 9.4). Changing a tenant's AI policy is the
decision that determines whether any tenant data may reach an LLM
provider at all -- the single most consequential switch in this module --
so it follows `telephony.call_recording`'s own precedent of an
owner-restricted capability rather than the usual owner/member parity.
`member` gets `read` so an ordinary user can see the tenant's AI posture
without being able to change it.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.ai.permissions import AI_POLICY_RESOURCE, grant_to_role
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = ((AI_POLICY_RESOURCE, ("read", "manage")),)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = ((AI_POLICY_RESOURCE, ("read",)),)


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
