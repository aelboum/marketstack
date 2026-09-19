"""Role/permission provisioning for the agency/client model
(docs/ROADMAP.md Phase 3.1-3.4).

Every `(resource, action)` pair granted to `AGENCY_OWNER_ROLE_NAME` below
is one of two kinds, and the distinction matters:

1. Core-owned capability names -- `invitation`, `membership_role`,
   `delegation_grant`, `deny_grant`, `support_access_request` -- these are
   NOT this product's own vocabulary. They are the exact, fixed resource/
   action strings hardcoded inside `core.identity.service.create_invitation()`,
   `core.rbac.service.assign_role()`, `create_delegation()`, `create_deny()`,
   `approve_support_access()`, etc. themselves (each one calls
   `core.rbac.register_permission(resource, action)` and then
   `core.rbac.can(...)` against that exact pair before doing anything).
   Granting them to a role is how a product gives an actor the standing
   authority those already-gated Core functions require -- this module
   does not invent them, it reads them off the real Core source
   (`core/identity/service.py`, `core/rbac/service.py`) and reuses them
   verbatim, mirroring exactly what `saas-os`'s own
   `examples/reference-consumer/reference_consumer/scenarios.py` does for
   its own admin roles.
2. `agency.client` (create/read) -- this one IS product-owned. Unlike
   every Core function above, `core.tenancy.create_tenant()` performs NO
   authorization check of its own (it is a "trusts its caller" primitive,
   the same category as `add_tenant_membership()`) -- so this product
   must supply its own gate before calling it, or any authenticated user
   who merely knows an agency's `tenant_id` could create tenants under
   it. See `product/agency/provisioning.py::provision_client()` and
   `docs/ADR/0002-...` for the full reasoning.

`CLIENT_MEMBER_ROLE_NAME`'s permission set was deliberately empty through
Phase 3 -- there was no business-domain permission to grant yet. Phase 4
is exactly the trigger Phase 3's own docstring anticipated -- but this
module does NOT import `product.crm` to grant its permissions directly
(that would violate `docs/ARCHITECTURE.md` section 2.2's "no
product/<module> imports another product/<module> directly" rule,
enforced by this repository's own import-linter contract: `product.crm`
and `product.agency` are both listed as independent siblings). Instead,
`provision_agency()` and `product/agency/onboarding.py
::assign_starting_client_role()` each publish an `agency.role_provisioned`
domain event (`product.foundation.events`, the one dependency every
module may use) after creating/assigning a role; `product/crm
/event_handlers.py` subscribes to it and grants its own permission set
reactively -- the exact "module needing another module's capability"
pattern `docs/ARCHITECTURE.md` section 2.2 itself prescribes (promote to
`foundation`, or react via the event dispatcher; this is the second
path). This module has no idea CRM exists.
"""

from __future__ import annotations

import uuid

from core.rbac import (
    Role,
    create_role,
    get_role_permission,
    grant_permission,
    list_roles,
    register_permission,
)

from product.foundation.events import Event, publish

AGENCY_OWNER_ROLE_NAME = "owner"
CLIENT_MEMBER_ROLE_NAME = "member"

# Published after either role below is created/looked-up, so any other
# module (product.crm, and any future module with its own tenant-scoped
# permissions) can react and grant its own permission set to it -- see
# module docstring. version=1: payload is {"role_id": str, "role_name":
# "owner"|"member"} -- a later, incompatible payload change bumps this.
ROLE_PROVISIONED_EVENT_TYPE = "agency.role_provisioned"
ROLE_PROVISIONED_EVENT_VERSION = 1


def _publish_role_provisioned(tenant_id: uuid.UUID, role: Role, role_name: str) -> None:
    publish(
        Event(
            type=ROLE_PROVISIONED_EVENT_TYPE,
            version=ROLE_PROVISIONED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"role_id": str(role.id), "role_name": role_name},
        )
    )


# The exact Core-owned (resource, action) pairs the agency owner role
# needs, one pair per Core capability this product's Phase 3 wraps.
_AGENCY_OWNER_CORE_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("invitation", "create"),
    ("invitation", "revoke"),
    ("membership_role", "create"),
    ("delegation_grant", "create"),
    ("delegation_grant", "revoke"),
    ("deny_grant", "create"),
    ("deny_grant", "revoke"),
    ("support_access_request", "approve"),
    ("support_access_request", "deny"),
    ("support_access_request", "revoke"),
)

# This product's own two permissions (see module docstring, kind 2).
AGENCY_CLIENT_RESOURCE = "agency.client"


def _get_or_create_role(tenant_id: uuid.UUID, name: str) -> Role:
    """Idempotent role lookup-or-create: `core.rbac.create_role()` itself
    enforces `uq_roles_tenant_name`, so a second call for the same
    `(tenant_id, name)` would raise -- this checks first via
    `list_roles()` (the same "find-or-create" discipline
    `api/tenant_bootstrap.py`'s own docstring uses for its own resumable
    steps), so provisioning helpers built on top of this stay safe to
    call more than once for the same tenant."""
    for role in list_roles(tenant_id):
        if role.name == name:
            return role
    return create_role(tenant_id, name)


def ensure_agency_owner_role(tenant_id: uuid.UUID) -> Role:
    """Create (idempotently) `tenant_id`'s own `"owner"` role, granting
    every Core-owned capability this product's Phase 3 wraps plus this
    product's own `agency.client` create/read -- see module docstring."""
    role = _get_or_create_role(tenant_id, AGENCY_OWNER_ROLE_NAME)
    for resource, action in (
        *_AGENCY_OWNER_CORE_PERMISSIONS,
        (AGENCY_CLIENT_RESOURCE, "create"),
        (AGENCY_CLIENT_RESOURCE, "read"),
    ):
        permission = register_permission(resource, action)
        # core.rbac.grant_permission() raises on a duplicate grant -- the
        # same idempotency concern _get_or_create_role() has above, so
        # check-then-grant via get_role_permission() rather than
        # grant-and-catch.
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)
    _publish_role_provisioned(tenant_id, role, AGENCY_OWNER_ROLE_NAME)
    return role


def ensure_client_member_role(tenant_id: uuid.UUID) -> Role:
    """Create (idempotently) `tenant_id`'s own `"member"` role. Grants no
    Core-owned permission itself (module docstring) -- publishes
    `agency.role_provisioned` so `product.crm` (and any future module)
    can grant its own baseline permission set reactively."""
    role = _get_or_create_role(tenant_id, CLIENT_MEMBER_ROLE_NAME)
    _publish_role_provisioned(tenant_id, role, CLIENT_MEMBER_ROLE_NAME)
    return role


def get_owner_role(tenant_id: uuid.UUID) -> Role | None:
    for role in list_roles(tenant_id):
        if role.name == AGENCY_OWNER_ROLE_NAME:
            return role
    return None
