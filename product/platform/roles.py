"""Role/permission provisioning for the platform-owner boundary
(docs/ROADMAP.md Phase 31). Mirrors `product/agency/roles.py`'s own
discipline exactly: this module's one product-owned resource is invented
here and nowhere else; nothing here duplicates a SaaS-OS-provided
authorization mechanism.

**One product-owned resource.** `PLATFORM_ADMINISTRATION_RESOURCE` is the
foundational capability this phase establishes -- deliberately generic
("administer"/"read" the platform's own scope), not a specific future
business operation (Phase 31's own "not every future platform operation"
scope limit). A later, separately-scoped phase that needs a more specific
platform-level permission (e.g. "read platform-wide subscription data")
registers its own resource the same way `product/billing/permissions.py`
registers `SUBSCRIPTION_RESOURCE` independently of this one -- this module
does not, and must not, grow into a dumping ground for every future
platform capability.

**Deliberately no Core-owned capability grants** (unlike
`product/agency/roles.py::ensure_agency_owner_role()`, which grants
`invitation`/`membership_role`/`delegation_grant`/`deny_grant`/
`support_access_request` create/revoke alongside its own resource): granting
those here would let a bootstrapped platform owner invite further members,
assign roles, and delegate/deny at the platform tenant today -- real
capability this phase's own scope explicitly does not build or test
("Platform Owner Capability Boundary": establish the foundational
authorization capability, not every future platform operation). Adding
them is exactly the documented, deliberate provisioning gap
`product/platform/provisioning.py::bootstrap_platform_tenant()`'s own
docstring names (granting platform ownership to a second user) --
future, separately-scoped work, not silently smuggled in here.
"""

from __future__ import annotations

import uuid

from core.authority import SystemAuthority, SystemCaller
from core.rbac import (
    Role,
    create_role,
    get_role_permission,
    grant_permission,
    list_roles,
    register_permission,
)

from product.foundation.events import Event, publish

PLATFORM_OWNER_ROLE_NAME = "platform_owner"

#: This product's own single platform-level resource (module docstring).
PLATFORM_ADMINISTRATION_RESOURCE = "platform.administration"
PLATFORM_ADMINISTRATION_ACTIONS: tuple[str, ...] = ("read", "administer")

# Published after the role below is created/looked-up, mirroring
# `product/agency/roles.py::ROLE_PROVISIONED_EVENT_TYPE`'s own reactive-
# grant pattern -- a future module that needs its own baseline permission
# set on the platform-owner role can subscribe to this instead of this
# module importing that module directly (docs/ARCHITECTURE.md section
# 2.2). No subscriber exists yet; publishing costs nothing and keeps this
# module consistent with every other role-provisioning module in this
# repository.
ROLE_PROVISIONED_EVENT_TYPE = "platform.role_provisioned"
ROLE_PROVISIONED_EVENT_VERSION = 1


def _publish_role_provisioned(tenant_id: uuid.UUID, role: Role) -> None:
    publish(
        Event(
            type=ROLE_PROVISIONED_EVENT_TYPE,
            version=ROLE_PROVISIONED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"role_id": str(role.id), "role_name": PLATFORM_OWNER_ROLE_NAME},
        )
    )


def _get_or_create_role(tenant_id: uuid.UUID, name: str) -> Role:
    """Idempotent role lookup-or-create -- identical discipline to
    `product/agency/roles.py::_get_or_create_role()` (`core.rbac.create_role()`
    itself enforces `uq_roles_tenant_name`, so a blind create on a second
    call would raise)."""
    for role in list_roles(tenant_id):
        if role.name == name:
            return role
    return create_role(tenant_id, name, caller=SystemCaller(SystemAuthority.PROVISIONING))


def ensure_platform_owner_role(tenant_id: uuid.UUID) -> Role:
    """Create (idempotently) `tenant_id`'s own `"platform_owner"` role,
    granting exactly this product's own `platform.administration`
    read/administer -- see module docstring for why no Core-owned
    capability is granted alongside it in this phase."""
    role = _get_or_create_role(tenant_id, PLATFORM_OWNER_ROLE_NAME)
    for action in PLATFORM_ADMINISTRATION_ACTIONS:
        permission = register_permission(PLATFORM_ADMINISTRATION_RESOURCE, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(
                tenant_id,
                role.id,
                permission.id,
                caller=SystemCaller(SystemAuthority.PROVISIONING),
            )
    _publish_role_provisioned(tenant_id, role)
    return role


def get_platform_owner_role(tenant_id: uuid.UUID) -> Role | None:
    for role in list_roles(tenant_id):
        if role.name == PLATFORM_OWNER_ROLE_NAME:
            return role
    return None


__all__ = [
    "PLATFORM_ADMINISTRATION_ACTIONS",
    "PLATFORM_ADMINISTRATION_RESOURCE",
    "PLATFORM_OWNER_ROLE_NAME",
    "ROLE_PROVISIONED_EVENT_TYPE",
    "ensure_platform_owner_role",
    "get_platform_owner_role",
]
