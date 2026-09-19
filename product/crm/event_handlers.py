"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own CRM permissions to the newly
provisioned role -- the "module needing another module's capability
reacts via the event dispatcher" path `docs/ARCHITECTURE.md` section 2.2
prescribes, since `product.crm` and `product.agency` must never import
each other directly (the independence contract this repository's own
`pyproject.toml` enforces).

**Subscribed at import time, module level** (`product.foundation.events
.subscribe()`'s own contract: a durable subscription must be registered
this way; this one uses the synchronous, in-process variant, which has
the same requirement in spirit -- the handler must be registered before
`product.agency.roles`'s own code publishes, which in this single-process
deployment means before any request is served). `product/api/main.py`
imports this module explicitly (a bare import, for its registration side
effect) so the subscription always exists by the time the app is ready
to serve traffic, regardless of which other module happens to import
`product.crm.routes` first.

The `owner` role is granted this product's full CRM permission set
(create/read/update/delete on every resource) -- an agency owner
manages its own and its clients' CRM data completely. The `member` role
(a client's own baseline role, `product/agency/roles.py
::CLIENT_MEMBER_ROLE_NAME`) is granted create/read/update, deliberately
NOT delete -- a baseline client member should not be able to permanently
remove CRM records by default (a judgment call, not a roadmap
requirement; revisit if a later phase needs a finer-grained role model).
`crm.pipeline` is granted read-only to the member role -- a member can
see pipeline/stage configuration without being able to change it.

**Phase 4.4 addition**: `crm.custom_field_definition`/`crm.tag` are
granted create+read to the owner role, but **read-only** to the member
role -- defining new custom fields or tags is treated as a schema-
shaping, owner-level configuration action (the same category as pipeline
configuration), not an ordinary record-level CRUD action; a member can
use fields/tags the owner has already defined (via the entity's own
`update` permission, per `product/crm/custom_fields.py`/`tags.py`'s own
consolidation principle) without being able to add new ones. Revisit if
a later phase needs client-configurable custom fields.
"""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.crm.permissions import (
    COMPANY_RESOURCE,
    CONTACT_RESOURCE,
    CUSTOM_FIELD_DEFINITION_RESOURCE,
    OPPORTUNITY_RESOURCE,
    PIPELINE_RESOURCE,
    TAG_RESOURCE,
    grant_to_role,
)
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CONTACT_RESOURCE, ("create", "read", "update", "delete")),
    (COMPANY_RESOURCE, ("create", "read", "update", "delete")),
    (OPPORTUNITY_RESOURCE, ("create", "read", "update", "delete")),
    (PIPELINE_RESOURCE, ("create", "read", "update", "delete")),
    (CUSTOM_FIELD_DEFINITION_RESOURCE, ("create", "read")),
    (TAG_RESOURCE, ("create", "read")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CONTACT_RESOURCE, ("create", "read", "update")),
    (COMPANY_RESOURCE, ("create", "read", "update")),
    (OPPORTUNITY_RESOURCE, ("create", "read", "update")),
    (PIPELINE_RESOURCE, ("read",)),
    (CUSTOM_FIELD_DEFINITION_RESOURCE, ("read",)),
    (TAG_RESOURCE, ("read",)),
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
