"""Product-defined permissions for `product/crm/` (docs/ROADMAP.md
Phase 4).

Unlike `product/agency/roles.py`'s Core-owned permission pairs (which
gate already-implemented `core.*` functions), every permission here is
this product's own invention -- `crm.*` tables have no SaaS-OS-provided
authorization of any kind, so nothing else gates them. Every mutating
and read `product/crm/*.py` service function calls `core.rbac.can()`
against one of these before touching a `crm.*` row (see
`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum for why this is mandatory, not a style choice).

Deliberately consolidated, not one resource per sub-entity: tasks and
notes attached to a contact/company/opportunity are gated by the SAME
permission as updating (for write) or reading (for read) the entity they
attach to -- there is no separate `crm.task`/`crm.note` resource. This
keeps the permission surface proportional to the number of independently
authorizable entities, not the number of tables.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.crm.errors import CrmAccessDeniedError

CONTACT_RESOURCE = "crm.contact"
COMPANY_RESOURCE = "crm.company"
OPPORTUNITY_RESOURCE = "crm.opportunity"
PIPELINE_RESOURCE = "crm.pipeline"
# Phase 4.4: defining a new custom field or tag (tenant-level schema
# configuration) is its own permission, distinct from populating/reading
# a *value* on a specific entity, which reuses that entity's own
# update/read permission (the same consolidation principle as tasks/notes).
CUSTOM_FIELD_DEFINITION_RESOURCE = "crm.custom_field_definition"
TAG_RESOURCE = "crm.tag"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirroring
    `product/agency/roles.py::ensure_agency_owner_role()`'s own
    check-then-grant discipline (`core.rbac.grant_permission()` raises on
    a duplicate grant)."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.crm.errors.CrmAccessDeniedError` unless `actor_user_id`
    holds `(resource, action)` at `tenant_id` -- the one authorization
    chokepoint every `product/crm/*.py` service function calls first,
    before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise CrmAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)
