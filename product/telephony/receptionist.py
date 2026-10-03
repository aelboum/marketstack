"""The AI receptionist actor (docs/ROADMAP.md Phase 27.1 -- "Call Session
& Actor Foundation"). Provisions the tenant-scoped identity Phase 26's
existing `invoke_product_ai_tool()`/`execute_approved_ai_tool()` will
invoke as, once a later phase (27.2) actually calls them from a live
call. This module never calls either of those functions itself -- see
`product/telephony/call_session.py`'s own module docstring for why.

**`core.identity.User`, never `core.rbac.PrincipalType.SERVICE_ACCOUNT`**
-- an explicit Phase 27.1 decision, not an oversight. `core/audit_log
/models.py::ActorType.USER`'s own docstring states plainly: "a
`core.identity` User (human or an AI agent -- ADR-0005 resolves both to
the same identity-context shape, so no separate 'agent' actor type is
needed)". A plain `User` row (`core/identity/models.py` -- just `id`/
`is_active`/timestamps, no required `ExternalIdentity` link) is already
fully sufficient: it participates in `core.rbac.can()`'s default
`actor_type=PrincipalType.USER` path -- the exact path
`control_plane.orchestration.service._is_authorized()` and
`product/ai/invocation.py::_tool_authorized()` already call, unchanged --
with zero code change anywhere in Phase 26, SaaS-OS, or Core. The
`PrincipalType.SERVICE_ACCOUNT` path is real and already fully built in
`core/rbac` (architecture research Phase E), but neither
`control_plane.orchestration` nor `product/ai/invocation.py` currently
thread `actor_type`/`actor_tenant_id` through to `core.rbac.can()` -- using
it would require extending those call sites first, which is explicitly out
of this phase's own scope (docs/ROADMAP.md Phase 27.1's own "Do NOT add
actor-type threading through Phase 26" instruction).

**One receptionist per tenant, never one per call or per turn.**
`ensure_ai_receptionist_actor()` is idempotent: a second call for the same
tenant returns the already-provisioned identity rather than creating a
duplicate. There is no dedicated table recording "this tenant's
receptionist user id" -- no migration is needed for that, because the
answer is already fully derivable from existing, already-queried state:
the receptionist's own dedicated role name is unique per tenant (`core.rbac
.create_role()`'s own `(tenant_id, name)` uniqueness), so idempotency is
established by looking for an existing active membership already holding
that role, exactly the same "list, then match, then create-if-absent"
discipline `product/agency/roles.py::_get_or_create_role()` already uses
for its own idempotent role provisioning -- reused here at the level of
"role plus its one assignment" instead of "role alone". As with that
existing helper, a race between two concurrent first-provisioning calls
for the same tenant is not closed by a database constraint (accepted here
for the identical reason `_get_or_create_role()`'s own docstring accepts
it: provisioning is an administrative, not a hot, path).

**No login, ever.** Provisioning never calls `core.identity
.link_external_identity()` -- the created `User` row has no linked OIDC
identity, so it structurally cannot authenticate through any real login
flow; it exists only to be named as an `actor_user_id` in an internal
`invoke_product_ai_tool()` call.

**Least privilege, deliberately incomplete here.** The dedicated role
this module creates (`RECEPTIONIST_ROLE_NAME`) is granted *zero*
permissions at provisioning time -- this phase does not yet know what
call-initiated business capabilities exist (that is Phase 27.2's own
scope: appointment booking, CRM lookups, and whatever specific
`(resource, action)` pairs those capabilities declare). Mirrors
`product/agency/roles.py::ensure_client_member_role()`'s own identical
"provision the role now, grant its real permission set later, once the
real capability exists" shape exactly -- never inventing a permission
speculatively. A future Phase 27.2 grants that role's own permissions via
`core.rbac.grant_permission()` against the `Role` this function returns;
this module has no idea what those will be and does not need to."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity import MembershipStatus, add_tenant_membership, create_user, list_tenant_members
from core.rbac import Role, RoleScope, assign_role, create_role, list_membership_roles, list_roles

RECEPTIONIST_ROLE_NAME = "ai_receptionist"


@dataclass(frozen=True, slots=True)
class AiReceptionistActor:
    """The provisioned identity 27.2 will later pass as `actor_user_id`
    to `invoke_product_ai_tool()`/`execute_approved_ai_tool()`, unchanged.
    Frozen: once provisioned, none of these ids is ever meant to change
    for the life of the tenant."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID


def _get_or_create_receptionist_role(tenant_id: uuid.UUID) -> Role:
    """Idempotent role lookup-or-create -- mirrors `product/agency/roles.py
    ::_get_or_create_role()` exactly (same reasoning, same accepted race)."""
    for role in list_roles(tenant_id):
        if role.name == RECEPTIONIST_ROLE_NAME:
            return role
    return create_role(
        tenant_id, RECEPTIONIST_ROLE_NAME, caller=SystemCaller(SystemAuthority.PROVISIONING)
    )


def _find_existing_receptionist(
    tenant_id: uuid.UUID, role_id: uuid.UUID
) -> AiReceptionistActor | None:
    """Is there already an ACTIVE membership in `tenant_id` holding
    `role_id`? Deliberately re-derived from existing `core.identity`/
    `core.rbac` state on every call rather than cached anywhere -- see
    module docstring's own "no dedicated table" reasoning."""
    for membership in list_tenant_members(tenant_id):
        if membership.status != MembershipStatus.ACTIVE.value:
            continue
        for membership_role in list_membership_roles(tenant_id, membership.id):
            if membership_role.role_id == role_id:
                return AiReceptionistActor(
                    tenant_id=tenant_id,
                    user_id=membership.user_id,
                    membership_id=membership.id,
                    role_id=role_id,
                )
    return None


def ensure_ai_receptionist_actor(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> AiReceptionistActor:
    """Provision (idempotently) `tenant_id`'s own dedicated AI receptionist
    actor. `actor_user_id` is the real, already-authenticated human (a
    tenant owner/admin) performing this provisioning step -- exactly the
    same role `product/agency/provisioning.py::provision_client()`'s own
    `actor_user_id` plays -- and must already hold this tenant's own
    `membership_role:create` capability, since this function's own final
    step is an ordinary `core.rbac.assign_role()` call, which enforces
    that itself (`RoleAssignmentNotAuthorizedError` otherwise, propagated
    unmodified -- never re-checked or re-wrapped here, per this
    repository's own "do not create Product-local equivalents of existing
    SaaS-OS authorization" convention). The anti-amplification check
    `assign_role()` also performs (the assigning actor must already hold
    every permission the role grants) is trivially satisfied here since
    the role starts with zero permissions -- module docstring.

    `scope=RoleScope.SELF` -- deliberately narrower than
    `provision_agency()`'s own `SUBTREE` grant for a human owner: the
    receptionist acts for exactly this one tenant, never its descendants."""
    role = _get_or_create_receptionist_role(tenant_id)

    existing = _find_existing_receptionist(tenant_id, role.id)
    if existing is not None:
        return existing

    user = create_user()
    membership = add_tenant_membership(
        tenant_id, user.id, caller=SystemCaller(SystemAuthority.PROVISIONING)
    )
    assign_role(
        tenant_id,
        membership.id,
        role.id,
        scope=RoleScope.SELF,
        caller=UserCaller(actor_user_id),
    )
    return AiReceptionistActor(
        tenant_id=tenant_id,
        user_id=user.id,
        membership_id=membership.id,
        role_id=role.id,
    )


__all__ = ["RECEPTIONIST_ROLE_NAME", "AiReceptionistActor", "ensure_ai_receptionist_actor"]
