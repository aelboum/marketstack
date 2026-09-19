"""Agency and client tenant provisioning (docs/ROADMAP.md Phase 3.1).

Tenancy mapping (see `docs/ADR/0003-agency-client-tenancy-mapping.md`
for the full reasoning and the rejected alternative): an **agency** is a
root `core.tenants` row (`parent_id IS NULL`) created through
`provision_agency()`; a **client** is a `core.tenants` row whose
`parent_id` is an agency tenant, created through `provision_client()`.
Neither concept has its own database table -- both are derived, at read
time, from `core.tenancy` alone. This module adds zero new tables and
zero new migrations.

Step ordering in both provisioning functions below deliberately mirrors
`saas-os`'s own `api/tenant_bootstrap.py` "safety argument" (its own
docstring: every step before the last produces only *inert* state, and
the authority-conferring step runs last) -- adapted here because, unlike
that operator CLI, the acting user already exists (they are already
authenticated before ever calling this product's own signup/provisioning
endpoints): tenant -> activation -> role (created, permissions granted,
still unassigned) -> membership -> role assignment (authority appears
here, and only here).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_first_role_for_new_tenant, can
from core.tenancy import (
    TenantStatus,
    create_tenant,
    get_descendant_ids,
    get_tenant,
    transition_tenant_status,
)

from product.agency.errors import AgencyAccessDeniedError
from product.agency.roles import AGENCY_CLIENT_RESOURCE, ensure_agency_owner_role


@dataclass(frozen=True, slots=True)
class Agency:
    tenant_id: uuid.UUID
    name: str
    owner_membership_id: uuid.UUID
    owner_role_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Client:
    tenant_id: uuid.UUID
    name: str
    agency_tenant_id: uuid.UUID


def provision_agency(actor_user_id: uuid.UUID, name: str) -> Agency:
    """Self-service agency signup: `actor_user_id` (an already-
    authenticated user -- see `product/agency/routes.py`) creates a new
    agency and becomes its owner, with a `SUBTREE`-scoped role so every
    client this agency creates in the future is automatically reachable
    with no further grant (`core.rbac.scope`'s own documented live-re-
    evaluation semantics) -- the one deliberate difference from
    `saas-os`'s own `examples/reference-consumer/reference_consumer
    /scenarios.py::provision_personal_tenant_for_new_user()`, which uses
    `RoleScope.SELF` because a personal tenant has no children to reach.

    Deliberately **ungated**: creating your own brand-new agency is the
    self-service signup case, exactly as ungated as
    `provision_personal_tenant_for_new_user()`'s own reference-consumer
    precedent -- there is no pre-existing tenant to check authority
    against yet.
    """
    tenant = create_tenant(name)
    transition_tenant_status(tenant.id, TenantStatus.ACTIVE)

    role = ensure_agency_owner_role(tenant.id)
    membership = add_tenant_membership(tenant.id, actor_user_id)
    # First role in a brand-new tenant -- no actor could hold the
    # anti-amplification authority assign_role() would otherwise demand,
    # since nothing has been granted in this tenant yet. Mirrors
    # reference-consumer's own identical use of this same explicit,
    # narrow trust boundary.
    assign_first_role_for_new_tenant(tenant.id, membership.id, role.id, scope=RoleScope.SUBTREE)

    return Agency(
        tenant_id=tenant.id,
        name=tenant.name,
        owner_membership_id=membership.id,
        owner_role_id=role.id,
    )


def provision_client(actor_user_id: uuid.UUID, agency_tenant_id: uuid.UUID, name: str) -> Client:
    """An agency creates a client tenant beneath it.

    `core.tenancy.create_tenant()` performs no authorization check of
    its own (module docstring; confirmed by reading its source directly
    -- it validates parent existence/lifecycle/depth only) -- so this
    function checks `core.rbac.can()` against this product's own
    `(resource="agency.client", action="create")` permission FIRST,
    before calling it, or any authenticated user who merely knows an
    agency's `tenant_id` could create tenants under it (the IDOR this
    function exists to close -- see `docs/ADR/0002-...`). This same
    `can()` call already fails closed for a SUSPENDED/DELETED/PURGING/
    PURGED agency tenant too (verified by reading
    `core/rbac/authorization.py::can()` directly: it re-locks and
    re-checks the target tenant's own lifecycle before evaluating any
    allow path) -- no separate lifecycle check is needed here.

    Deliberately **no first-role bootstrap at the client**: the agency
    owner's pre-existing `SUBTREE` role (granted in `provision_agency()`)
    already reaches this tenant the instant it exists -- that is the
    entire point of `SUBTREE`'s live-re-evaluation semantics
    (`core/tenancy/service.py::move_tenant()`'s own docstring: "If a
    descendant is later moved out of the subtree (or a new one moved
    in), the assignment's reach changes automatically, with no rewrite
    of the assignment row itself"). Calling
    `assign_first_role_for_new_tenant()` here would be unnecessary and
    would incorrectly suggest the client tenant starts with no owner
    reach, which is false.
    """
    if not can(
        actor_id=actor_user_id,
        tenant_id=agency_tenant_id,
        action="create",
        resource=AGENCY_CLIENT_RESOURCE,
    ):
        raise AgencyAccessDeniedError(actor_user_id, agency_tenant_id)

    tenant = create_tenant(name, parent_id=agency_tenant_id)
    transition_tenant_status(tenant.id, TenantStatus.ACTIVE)

    return Client(tenant_id=tenant.id, name=tenant.name, agency_tenant_id=agency_tenant_id)


def list_clients(actor_user_id: uuid.UUID, agency_tenant_id: uuid.UUID) -> list[Client]:
    """Every client currently beneath `agency_tenant_id`. Assumes the
    flat, 2-level hierarchy this phase establishes (`docs/ADR/0003-...`)
    -- every descendant of the agency is treated as a direct client; a
    future deeper hierarchy (e.g. sub-agencies) would need this function
    revisited, not silently reused."""
    if not can(
        actor_id=actor_user_id,
        tenant_id=agency_tenant_id,
        action="read",
        resource=AGENCY_CLIENT_RESOURCE,
    ):
        raise AgencyAccessDeniedError(actor_user_id, agency_tenant_id)

    descendant_ids = get_descendant_ids(agency_tenant_id) - {agency_tenant_id}
    clients = []
    for client_tenant_id in descendant_ids:
        tenant = get_tenant(client_tenant_id)
        clients.append(
            Client(tenant_id=tenant.id, name=tenant.name, agency_tenant_id=agency_tenant_id)
        )
    return clients
