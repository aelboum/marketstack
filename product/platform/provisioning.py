"""Platform tenant bootstrap (docs/ROADMAP.md Phase 31 -- Platform
Ownership Foundation).

**ARCHITECTURAL DECISION (made from repository evidence, per Phase 31's
own "do not guess" requirement).**

Phase 31 named two options and required a decision between them before
implementation. This module implements **Option A** (a platform tenant
reusing the existing `core.tenancy` hierarchy and `core.rbac` `SUBTREE`
scope) -- **Option B (a dedicated `PLATFORM_OPERATOR` principal type) is
rejected for this implementation**, for one specific, verified reason:

`core/rbac/principal.py::PrincipalType` is a closed, three-member
`StrEnum` (`USER`, `SYSTEM`, `SERVICE_ACCOUNT`), and its own module
docstring explicitly records `PLATFORM_OPERATOR` as considered and
rejected by SaaS-OS's own architecture research ("still out of scope").
`core/rbac/authorization.py::can()` dispatches on this exact enum --
`actor_type is PrincipalType.USER` / `elif actor_type is
PrincipalType.SERVICE_ACCOUNT` / `else: return False` -- so a genuine
platform-wide principal distinct from an ordinary tenant-scoped user
would require adding a fourth `PrincipalType` member and a third dispatch
branch inside `can()` itself: a SaaS-OS change. Phase 31's own hard scope
("Do NOT modify SaaS-OS... If Option B would require changes to SaaS-OS
authorization primitives, STOP and report") makes that path unavailable
to this implementation. No product-level workaround exists that avoids
this without either (a) building a second, competing authorization
engine outside `can()` (explicitly forbidden -- "do not create a second
authorization engine"), or (b) not actually being a *platform-wide*
principal at all, which is what Option B specifically asked for.

Option A requires none of that: `core.tenancy.create_tenant()`,
`core.rbac.create_role()`/`register_permission()`/`grant_permission()`/
`assign_first_role_for_new_tenant()` are all already-public,
already-used-by-`product.agency` SaaS-OS functions. A platform tenant is
created through the exact same public API `product/agency/provisioning.py
::provision_agency()` already uses for an agency tenant -- this module
adds no new SaaS-OS surface, no new table, no new migration, and (per
this module's own bootstrap function below) does not touch any existing
agency's `parent_id` at all.

**What this buys, concretely**: `core/rbac/authorization.py::can()`
already walks a `SUBTREE`-scoped role up from any target tenant through
`core.tenancy.get_ancestor_ids()`. Once a real tenant becomes a
descendant of the platform tenant -- via `attach_agency_to_platform()`
below, the explicit, gated, one-Agency-at-a-time mechanism this phase's
own completion audit added -- the platform owner's `SUBTREE` role reaches
it automatically, with zero authorization-code change -- satisfying Phase
31's own requirement 10 ("can support a future Platform Owner UI without
inventing a second architecture later").

**`bootstrap_platform_tenant()` itself reparents nothing.** The platform
tenant it creates initially has ONLY itself in its own subtree -- every
agency this repository already has, and every agency `provision_agency()`
creates afterward, remains a root tenant (`parent_id IS NULL`) exactly as
before, unless and until a platform owner separately, explicitly calls
`attach_agency_to_platform()` below for that one named Agency. This is
deliberate (Phase 31's own "do not silently reparent tenants"): safe
reparenting is never an incidental side effect of bootstrapping the
platform tenant, and is always an explicit, gated, audited, one-Agency-
at-a-time operator action -- see `attach_agency_to_platform()`'s own
docstring for the mechanism this phase's own completion audit added.

**Resolving "the" platform tenant, deterministically, without a new
table.** `core.tenants.name` has no uniqueness constraint (`core/tenancy
/service.py::find_tenants_by_name()`'s own docstring) -- and, concretely,
`product/agency/provisioning.py::provision_agency()` lets any
self-service caller name their own agency anything at all, including
`"Platform"`. Resolving the platform tenant by name would therefore be
genuinely ambiguous, not merely theoretically so: an ordinary agency
signup could collide with it. This module instead resolves the platform
tenant through one externally-configured value, `PLATFORM_TENANT_ID`
(read via `os.environ`, mirroring `product/telephony/adapters
/twilio_config.py::get_twilio_config()`'s own "one well-known,
operator-set, non-secret configuration value" pattern exactly) -- set
once, by whoever runs `bootstrap_platform_tenant()`, after it returns.
This is the documented provisioning mechanism (see that function's own
docstring), not a public API, and not a second tenancy abstraction: the
env var names an ordinary `core.tenants` row, nothing more.

**Documented provisioning gap (Phase 31's own "if no safe existing
mechanism exists, implement only the minimal internal foundation and
document the provisioning gap" instruction)**: this module provisions
exactly one platform owner, at bootstrap time. Granting platform
ownership to a *second*, later user is deliberately NOT built here --
doing so safely needs an existing platform owner to perform the grant
(the ordinary `core.rbac.assign_role()` anti-amplification path, not a
bootstrap-only shortcut), which is real, separately-testable capability
this foundation phase does not build (Phase 31's own "not every future
platform operation" scope limit). Until that future phase exists, a
second platform owner can only be added by directly calling
`core.identity.add_tenant_membership()` + `core.rbac.assign_role()`
against the already-bootstrapped platform tenant, as an existing platform
owner (or an equivalent controlled operational action) -- not through any
function this module exports.

**Phase 31 completion (ownership-relationship audit/correction):
`attach_agency_to_platform()`.** A platform tenant that reaches no
Agency is not a functioning ownership foundation: `core/rbac/authorization
.py::can()`'s `SUBTREE` walk is evaluated from the *target* tenant
upward through `core.tenancy.get_ancestor_ids()` -- so the platform
owner's `SUBTREE` role at the platform tenant authorizes an Agency (or a
Client beneath it) if and only if that Agency is a genuine descendant of
the platform tenant in `core.tenant_ancestry`. Confirmed by reading both
modules directly, not assumed. `attach_agency_to_platform()` is the one
function this module adds to establish that edge, for exactly one
explicitly-named Agency root tenant at a time -- never a bulk migration
that enumerates every tenant in the system, since neither `core.tenancy`
nor `product.agency` publishes such a listing (an agency has no owning
row of its own to enumerate -- `product/agency/provisioning.py`'s own
module docstring: "Neither concept has its own database table"), and
adding one would itself be a SaaS-OS change this phase's hard scope
forbids. An operator (an existing platform owner) supplies the Agency's
own `tenant_id`, exactly as they already must know it to run any other
one-off operational action against it.

**New agencies deliberately remain independent roots by default.**
`product/agency/provisioning.py::provision_agency()` is intentionally
left unchanged: `product.agency` carries an enforced import-linter
"independence" contract against every other product module including
`product.platform` (`pyproject.toml`'s "Agency does not depend on any
product module except Templates" contract, confirmed by reading it
directly) -- self-service agency signup structurally cannot import this
module to auto-attach itself under the platform tenant without a
cross-module coupling this phase's hard scope does not authorize
("preserve existing agency owner provisioning"; no redesign of
Agency -> Client). Newly created agencies are therefore attachable
through this exact same function, on the identical operator-driven,
explicit, audited path as any pre-existing agency -- attachment is a
deliberate act, not an automatic side effect of signup, consistent with
this phase's own "not every future platform operation" scope limit.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from core.audit_log import ActorType, AuditOutcome
from core.audit_log import record as record_audit_event
from core.idempotency import (
    IdempotencyInProgressError,
    IdempotencyStatus,
    begin_idempotent_operation,
    finalize_idempotent_operation,
)
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_first_role_for_new_tenant, can
from core.tenancy import (
    Tenant,
    TenantStatus,
    create_tenant,
    get_tenant,
    move_tenant,
    transition_tenant_status,
)

from product.platform.errors import (
    PlatformAccessDeniedError,
    PlatformAttachTargetNotRootTenantError,
    PlatformSelfAttachError,
    PlatformTenantAlreadyBootstrappedError,
    PlatformTenantNotBootstrappedError,
    PlatformTenantNotRootError,
)
from product.platform.roles import PLATFORM_ADMINISTRATION_RESOURCE, ensure_platform_owner_role

#: The one environment variable naming the bootstrapped platform tenant --
#: see module docstring's "Resolving 'the' platform tenant" section. Not a
#: secret (it names a tenant id, nothing else) -- mirrors
#: `TWILIO_VOICE_CALLBACK_BASE_URL`'s own non-secret-configuration
#: precedent, not `docs/ADR/0012-secrets-management.md`'s secret handling.
PLATFORM_TENANT_ID_ENV_VAR = "PLATFORM_TENANT_ID"

#: Display name only (`core.tenants.name` has no uniqueness constraint --
#: module docstring) -- never used to resolve "the" platform tenant.
PLATFORM_TENANT_DISPLAY_NAME = "Platform"


@dataclass(frozen=True, slots=True)
class PlatformTenant:
    tenant_id: uuid.UUID
    name: str
    owner_membership_id: uuid.UUID
    owner_role_id: uuid.UUID


def _configured_platform_tenant_id() -> uuid.UUID | None:
    raw = os.environ.get(PLATFORM_TENANT_ID_ENV_VAR)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        # Malformed configuration is treated identically to "not
        # configured" (fail closed to "no platform tenant exists" rather
        # than raising a confusing low-level ValueError from deep inside
        # an authorization check) -- an operator fixes the env var, the
        # same way a malformed TWILIO_VOICE_CALLBACK_BASE_URL fails
        # closed in `product/telephony/adapters/twilio_config.py`.
        return None


def bootstrap_platform_tenant(actor_user_id: uuid.UUID) -> PlatformTenant:
    """One-time bootstrap: create the platform tenant and assign
    `actor_user_id` as its first `platform_owner`, with a `SUBTREE`-scoped
    role (mirrors `product/agency/provisioning.py::provision_agency()`'s
    own identical shape and reasoning -- every future descendant of this
    tenant is automatically reachable with no further grant).

    Refuses if `PLATFORM_TENANT_ID` is already configured
    (`PlatformTenantAlreadyBootstrappedError`) -- this is a one-time
    bootstrap, not an idempotent "ensure" call (module docstring's
    documented provisioning gap: adding a further owner later is a
    deliberately separate, not-yet-built operation).

    Deliberately **ungated**, exactly like `provision_agency()`: there is
    no pre-existing platform tenant to check authority against on the
    very first call, and this function is never reachable through an
    HTTP route (Phase 31's own "no public self-service platform-owner
    registration endpoint" requirement) -- it is meant to be invoked once,
    by a controlled operational action (e.g. a one-off script run by
    whoever operates this deployment), with `PLATFORM_TENANT_ID` set from
    its result immediately afterward.
    """
    already_configured = _configured_platform_tenant_id()
    if already_configured is not None:
        raise PlatformTenantAlreadyBootstrappedError(already_configured)

    tenant = create_tenant(PLATFORM_TENANT_DISPLAY_NAME)
    transition_tenant_status(tenant.id, TenantStatus.ACTIVE)

    role = ensure_platform_owner_role(tenant.id)
    membership = add_tenant_membership(tenant.id, actor_user_id)
    # First role in a brand-new tenant -- identical reasoning to
    # provision_agency()'s own use of this same narrow trust boundary: no
    # actor could hold assign_role()'s anti-amplification authority yet,
    # since nothing has been granted in this tenant before this line.
    assign_first_role_for_new_tenant(tenant.id, membership.id, role.id, scope=RoleScope.SUBTREE)

    return PlatformTenant(
        tenant_id=tenant.id,
        name=tenant.name,
        owner_membership_id=membership.id,
        owner_role_id=role.id,
    )


def get_platform_tenant() -> Tenant:
    """Resolve the bootstrapped platform tenant via `PLATFORM_TENANT_ID`
    (module docstring). Raises `PlatformTenantNotBootstrappedError` if
    unset/malformed -- a normal, expected state before bootstrap has run,
    never a data-integrity fault. A configured id that no longer names a
    real tenant raises `core.tenancy.TenantNotFoundError` unchanged (a
    genuine misconfiguration an operator must fix, deliberately NOT
    caught here -- see `product.platform.authorization
    .has_platform_authority()`'s own docstring for why that function
    treats these two failure modes differently).

    **Root validation (audit remediation, Finding A).** A configured id
    that names a real but NON-root tenant (`parent_id is not None`) raises
    `PlatformTenantNotRootError` -- distinct from both failure modes
    above: "not configured" (silently, safely denies every platform
    check) and "not this tenant" (`TenantNotFoundError`, an operator typo)
    are both operationally recoverable by fixing the env var; a real,
    existing, NON-root tenant is a structurally wrong configuration that
    would otherwise let `attach_agency_to_platform()` silently reparent an
    Agency under the wrong tenant, believing it to be the platform root.
    This is configuration validation only -- it performs no authorization
    check of its own (`has_platform_authority()`'s own contract is
    unchanged), and it never silently reinterprets a non-root tenant as
    "not bootstrapped": callers that only handle
    `PlatformTenantNotBootstrappedError` will see this new, distinctly
    named error surface instead, exactly as they already see
    `TenantNotFoundError` surface unchanged for a dangling id."""
    tenant_id = _configured_platform_tenant_id()
    if tenant_id is None:
        raise PlatformTenantNotBootstrappedError()
    tenant = get_tenant(tenant_id)
    if tenant.parent_id is not None:
        raise PlatformTenantNotRootError(tenant.id, tenant.parent_id)
    return tenant


#: `core.audit_log` action name for `attach_agency_to_platform()` --
#: mirrors `core/tenancy/service.py`'s own fixed, closed action-name
#: vocabulary for lifecycle events (module docstring's "Lifecycle audit
#: evidence" section), never free text.
_ACTION_AGENCY_ATTACHED = "platform.agency_attached"
_AUDIT_RESOURCE_TYPE = "tenant"

#: `core.idempotency` operation name for `attach_agency_to_platform()`'s
#: audit-record race-fix (module docstring's own "Audit correctness"
#: section below) -- deterministic, never free text, mirrors
#: `_ACTION_AGENCY_ATTACHED`'s own fixed-vocabulary discipline.
_IDEMPOTENCY_OPERATION_ATTACH_AGENCY = "platform.attach_agency"


def attach_agency_to_platform(actor_user_id: uuid.UUID, agency_tenant_id: uuid.UUID) -> Tenant:
    """Make `agency_tenant_id` -- an Agency root tenant (`parent_id IS
    NULL`), existing or newly provisioned -- a child of the bootstrapped
    platform tenant, so the platform owner's `SUBTREE` role reaches it (and
    every Client already beneath it) through `core.rbac.authorization
    .can()`'s ordinary ancestor walk, with zero further grant (module
    docstring's "Phase 31 completion" section).

    **Gated**, unlike `bootstrap_platform_tenant()`: a platform tenant
    already exists by the time this is ever called, so the ordinary
    anti-amplification discipline applies -- `actor_user_id` must already
    hold `(PLATFORM_ADMINISTRATION_RESOURCE, "administer")` at the
    platform tenant itself (`PlatformAccessDeniedError` otherwise),
    mirroring `product/agency/provisioning.py::provision_client()`'s own
    `can()`-before-mutation discipline exactly.

    **Refuses to move anything but an Agency root**: raises
    `PlatformSelfAttachError` if `agency_tenant_id` is the platform tenant
    itself, and `PlatformAttachTargetNotRootTenantError` if it already has
    a parent other than the platform tenant (e.g. it is actually a Client
    tenant) -- this function is deliberately not a general `move_tenant()`
    wrapper (module docstring). Already being a child of the platform
    tenant is accepted as a no-op (idempotent), delegated to
    `core.tenancy.move_tenant()`'s own documented no-op-move behavior --
    calling this twice for the same Agency is safe.

    Delegates the move itself entirely to `core.tenancy.move_tenant()`
    (unchanged, already-public SaaS-OS API): tenant id, memberships, roles,
    and every Client already beneath `agency_tenant_id` are preserved
    exactly -- `move_tenant()`'s own docstring: "Moves the hierarchy
    relationship only... Never touches tenant-owned business data" and
    "Ancestry rows internal to the subtree... are unaffected". The
    Agency's own owner keeps its identical `SUBTREE` reach over its
    Clients (never touched); it gains no reach toward the platform tenant
    or any sibling Agency (the ancestor walk only goes *up* from a target
    tenant, and the platform tenant does not become the Agency's
    descendant).

    **Audited**: `move_tenant()` itself writes no audit record (confirmed
    by reading `core/tenancy/service.py` directly -- unlike
    `transition_tenant_status()`/`purge_tenant()`, it logs nothing on its
    own). Since this is the one operation in this phase that changes an
    existing Agency's place in the hierarchy, this function writes its own
    `core.audit_log` entry, attributed to `agency_tenant_id` (the tenant
    whose position changed) -- bounded metadata only (ids, never a tenant
    name or any customer content), mirroring `core/tenancy/service.py
    ::_record_lifecycle_event()`'s own shape.

    **Audit correctness under concurrent duplicate attachment (audit
    remediation, Finding B).** `move_tenant()` itself exposes no signal
    distinguishing "I just performed the move" from "it was already done,
    I no-op'd" -- both return an indistinguishable `Tenant`. A pre-move
    read of `agency_tenant.parent_id` (what this function used to gate
    the audit write on) is provably insufficient: two callers racing to
    attach the same not-yet-attached Agency can both observe
    `parent_id is None` before either has moved it, so both would
    conclude "I attached it" and both would write an
    `_ACTION_AGENCY_ATTACHED` record for what is structurally one real
    move plus one `move_tenant()`-guaranteed no-op. Fixed by reusing
    `core.idempotency.begin_idempotent_operation()`/
    `finalize_idempotent_operation()` -- the existing, already-public
    SaaS-OS primitive this repository already relies on for exactly "an
    operation that wraps an external call managing its own transaction"
    (`core.billing.service.subscribe_idempotent()`'s identical shape;
    `move_tenant()`'s own `session_scope()` is that external call here,
    the same reason `core.idempotency.run_idempotent()`'s single-
    transaction coupling is not usable -- mirrors
    `product/websites/leads.py`'s own documented reason for the identical
    choice). Keyed deterministically by `(platform_tenant.id, "platform
    .attach_agency", str(agency_tenant_id))` -- never a caller-supplied or
    random key, so every concurrent or later call for the *same* Agency
    collides on the *same* reservation, resolved by Postgres's own unique-
    index contention (module docstring of `core/idempotency/service.py`),
    not an application-level lock. Exactly one caller wins a fresh
    reservation (`is_replay=False`) and is the one that writes the audit
    record, after `move_tenant()` actually resolves (`FAILED` on any
    exception, so a real failure never leaves a stale `PENDING` record
    blocking a future retry -- re-raised unchanged afterward). Every other
    caller either replays an already-`SUCCEEDED` reservation
    (`is_replay=True`) or, for a genuinely concurrent duplicate landing
    while the winner's reservation is still `PENDING`, catches
    `IdempotencyInProgressError` -- both cases skip the audit write
    entirely, but **still call `move_tenant()` themselves, unconditionally**,
    exactly as before: this function's own "safe to call more than once,
    never raises for an already-attached Agency" guarantee is completely
    unchanged, only the audit-record decision is now race-free.
    """
    platform_tenant = get_platform_tenant()

    if not can(
        actor_id=actor_user_id,
        tenant_id=platform_tenant.id,
        action="administer",
        resource=PLATFORM_ADMINISTRATION_RESOURCE,
    ):
        raise PlatformAccessDeniedError(
            actor_user_id, resource=PLATFORM_ADMINISTRATION_RESOURCE, action="administer"
        )

    if agency_tenant_id == platform_tenant.id:
        raise PlatformSelfAttachError(platform_tenant.id)

    agency_tenant = get_tenant(agency_tenant_id)
    if agency_tenant.parent_id is not None and agency_tenant.parent_id != platform_tenant.id:
        raise PlatformAttachTargetNotRootTenantError(agency_tenant_id, agency_tenant.parent_id)

    should_record_attachment = False
    reservation_record_id: uuid.UUID | None = None
    try:
        reservation = begin_idempotent_operation(
            platform_tenant.id,
            _IDEMPOTENCY_OPERATION_ATTACH_AGENCY,
            str(agency_tenant_id),
            {
                "agency_tenant_id": str(agency_tenant_id),
                "platform_tenant_id": str(platform_tenant.id),
            },
        )
        if not reservation.is_replay:
            should_record_attachment = True
            reservation_record_id = reservation.record_id
    except IdempotencyInProgressError:
        # A genuinely concurrent duplicate, racing the reservation winner
        # right now -- module docstring's own "no audit record, still call
        # move_tenant()" resolution.
        pass

    try:
        moved = move_tenant(agency_tenant_id, platform_tenant.id)
    except Exception:
        if reservation_record_id is not None:
            finalize_idempotent_operation(
                platform_tenant.id, reservation_record_id, status=IdempotencyStatus.FAILED
            )
        raise

    if reservation_record_id is not None:
        finalize_idempotent_operation(
            platform_tenant.id,
            reservation_record_id,
            status=IdempotencyStatus.SUCCEEDED,
            result={"agency_tenant_id": str(agency_tenant_id)},
        )

    if should_record_attachment:
        record_audit_event(
            tenant_id=agency_tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action=_ACTION_AGENCY_ATTACHED,
            resource_type=_AUDIT_RESOURCE_TYPE,
            resource_id=str(agency_tenant_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"platform_tenant_id": str(platform_tenant.id)},
        )

    return moved


__all__ = [
    "PLATFORM_TENANT_DISPLAY_NAME",
    "PLATFORM_TENANT_ID_ENV_VAR",
    "PlatformTenant",
    "attach_agency_to_platform",
    "bootstrap_platform_tenant",
    "get_platform_tenant",
]
