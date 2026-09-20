"""Client onboarding and membership (docs/ROADMAP.md Phase 3.2).

**Resolved 2026-09-19 -- history preserved below, read before touching
this file.** `core.identity.service.accept_invitation()` used to be
documented, in its own docstring at the previously-pinned commit
(`2a299a3b5fa62e810d87e3ff2d8e844763e6a38b`), as "Currently non-
functional end to end, by deliberate design trade-off (Privacy
Architecture Audit finding PRIV-01)... this function always raises
InvitationInvalidError, for every token, valid or not" -- `core
.invitations` is fully RLS-protected and the function's token-resolution
step had no tenant context yet to scope that read to. That was SaaS-OS's
own acknowledged gap, never a defect introduced here, and never one this
product could fix itself (it would have meant editing `core.invitations`'
RLS policy or `accept_invitation()`'s own tenant-resolution step, both
inside `saas-os`). No product-side workaround was ever built while this
was blocked, per that same reasoning.

It is now fixed upstream, in SaaS-OS commit
`1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6` ("fix: restore invitation
acceptance and delegation scope consistency"): `accept_invitation()` now
takes a required `tenant_id` parameter and resolves the token inside
`infra.db.tenant_session_scope(tenant_id)` from the start -- no untenanted
read, no RLS gap. `tenant_id` is used **only** to scope the lookup, never
as a source of authority: a `tenant_id` that does not match the token's
own real invitation simply finds no row and raises the identical
`InvitationInvalidError` as any other failure (unknown/expired/revoked/
already-accepted token) -- the token itself remains the sole bearer
credential, exactly as before. This product now consumes that fixed API
directly (`accept_client_invitation()` below passes `tenant_id` straight
through, unchanged pass-through, zero product-side validation logic
added) -- see `docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s
"Related, separately-tracked SaaS-OS limitation" section for the full
history and its own "Resolved" note.

`invite_client_member()` (the send half) has worked since Phase 3 first
shipped and is unchanged. `accept_client_invitation()` (the accept half)
now genuinely works end-to-end, tested against a real disposable
Postgres in `tests/agency/test_onboarding_integration.py`.
`assign_starting_client_role()` (the third step -- give the newly-
accepted member their baseline role) remains its own, independently
callable function, still independently testable on its own.

**Remediation -- discovered during UI-2 review.** The paragraph above
used to end "...now chained for real after a genuine acceptance in the
happy-path integration test" -- true, but misleading: chained in a
*test*, never in the actual `accept_client_invitation()` this module
exports, nor in `product/agency/routes.py::accept_invitation_route`. A
real accepted invitation left the new member with a bare
`TenantMembership` and no role -- `core.rbac.can()` denies everything
for them until someone separately, manually, calls
`assign_starting_client_role()`, and no route ever exposed a way to do
that either. `accept_client_invitation()` below now performs that third
step itself, chained straight onto a successful acceptance -- see its
own docstring for the actor-authority reasoning (who is allowed to grant
that role, and how this function gets hold of them) and for exactly what
"chained" does and does not guarantee transactionally.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.identity import (
    Invitation,
    TenantMembership,
    accept_invitation,
    create_invitation,
    list_invitations_for_tenant,
)
from core.rbac import DuplicateRoleAssignmentError, MembershipRole, RoleScope, assign_role

from product.agency.roles import ensure_client_member_role


@dataclass(frozen=True, slots=True)
class InvitationSent:
    invitation_id: uuid.UUID
    tenant_id: uuid.UUID
    raw_token: str


def invite_client_member(
    actor_user_id: uuid.UUID, client_tenant_id: uuid.UUID, invited_email: str
) -> InvitationSent:
    """Invite `invited_email` to join `client_tenant_id`. No extra
    product-side authorization gate is needed here -- `core.identity
    .create_invitation()` already self-authorizes via `core.rbac.can()`
    against `(resource="invitation", action="create")`, which the
    inviting agency's owner role holds (via its `SUBTREE` reach into this
    client, or via a client's own direct member holding it locally)."""
    invitation, raw_token = create_invitation(client_tenant_id, actor_user_id, invited_email)
    return InvitationSent(
        invitation_id=invitation.id, tenant_id=client_tenant_id, raw_token=raw_token
    )


def accept_client_invitation(
    raw_token: str, accepting_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> TenantMembership:
    """Redeem `raw_token` for `tenant_id` (see module docstring for the
    full history). `tenant_id` is whatever tenant the invitation link the
    accepting user followed said it belonged to (e.g. `InvitationSent
    .tenant_id`, carried alongside the token into whatever future
    ingress/email flow constructs a real accept link) -- this function
    performs zero validation of its own that `tenant_id` is correct
    before calling `core.identity.accept_invitation()`; none is needed,
    because that function's own RLS-scoped lookup is the complete,
    correct validation (a wrong `tenant_id` simply finds no row and
    raises the same `InvitationInvalidError` as any other invalid token).
    Adding a product-side pre-check here would be redundant at best, and
    would require reading `core.invitations` directly at worst -- both
    out of bounds.

    **Chains into `assign_starting_client_role()`** on a successful
    accept (module docstring's "Remediation" note) -- the third step the
    Phase 3.2 acceptance criterion always asked for ("land in their own
    tenant with the correct starting role"), now actually reached.

    *Which actor grants the role, and why that's not a widened trust
    boundary*: `assign_starting_client_role()` needs an `actor_user_id`
    already holding `(resource="membership_role", action="create")`
    authority at `tenant_id` -- the accepting user themselves never has
    that (they hold no role at all the instant before this runs), so
    this function uses the invitation's own `inviter_user_id`
    (`core.identity.Invitation`) instead: exactly the actor
    `product/agency/routes.py::create_invitation_route()` already
    required to hold `(resource="invitation", action="create")`
    authority to send this invitation in the first place, and
    `roles.py::ensure_agency_owner_role()` grants that same actor
    `membership_role:create` too (both are in `_AGENCY_OWNER_CORE_PERMISSIONS`
    together) -- so this never grants more than that actor could already
    do directly. `assign_role()`'s own anti-amplification check
    (`core/rbac/service.py`) re-verifies this live regardless: if the
    inviter's authority was revoked between invite and accept, role
    assignment fails and that failure is not caught here (see below) --
    never a silent widening of who "the inviter" is trusted to be.

    `accept_invitation()` returns only the resulting `TenantMembership`,
    never the `Invitation` row it consumed, so `_resolve_inviter_user_id()`
    below re-resolves the inviter via `core.identity
    .list_invitations_for_tenant()` -- the one read primitive Core
    exposes for this -- rather than a second, redundant token-hash
    lookup (there is no, and should be no, public "peek without
    accepting" primitive).

    *Not one atomic transaction*: `accept_invitation()` above already
    committed the membership, inside its own `tenant_session_scope`,
    entirely inside `core.identity` -- this product cannot reach into
    that transaction, and does not try to. `assign_starting_client_role()`
    commits its own role-assignment in a second, independently-atomic
    transaction. If that second step raises, the membership still exists
    without a role, and the exception below is **not** swallowed -- it
    propagates to this function's own caller
    (`product/agency/routes.py::accept_invitation_route`), which reports
    the real failure rather than a misleadingly-successful 200. The one
    exception this function does treat as success:
    `DuplicateRoleAssignmentError`, raised when this exact membership
    already holds this exact role -- the documented idempotent case
    (`core.identity.accept_invitation()`'s own "an already-ACTIVE
    membership is a no-op success, but the token is still consumed"
    behavior means a second accepted invitation for an existing member
    can reach here with a membership that was already given its starting
    role the first time)."""
    membership = accept_invitation(raw_token, accepting_user_id, tenant_id)

    inviter_user_id = _resolve_inviter_user_id(tenant_id, accepting_user_id)
    # `accept_invitation()` above just set `accepted_by_user_id` on the
    # exact invitation row this call consumed, in the same tenant, inside
    # a transaction that has already committed by the time it returned --
    # a caller-visible failure to find it here would mean that guarantee
    # itself broke, not a normal, expected outcome worth a quieter
    # failure mode.
    assert inviter_user_id is not None, (
        f"accept_invitation() succeeded for tenant {tenant_id} but no invitation "
        f"accepted by {accepting_user_id} could be found afterward."
    )

    try:
        assign_starting_client_role(inviter_user_id, tenant_id, membership.id)
    except DuplicateRoleAssignmentError:
        pass

    return membership


def _resolve_inviter_user_id(
    tenant_id: uuid.UUID, accepting_user_id: uuid.UUID
) -> uuid.UUID | None:
    """The `inviter_user_id` of whichever invitation `accepting_user_id`
    most recently accepted in `tenant_id`. Picks the most recently
    `accepted_at` match among that user's accepted invitations to this
    tenant, in case there is more than one (see
    `accept_client_invitation()`'s own docstring for why that can
    happen) -- `accepted_at` is guaranteed non-`None` for every candidate
    here (`core.identity.Invitation`'s own
    `ck_invitations_acceptance_pairing` CHECK constraint: paired with
    `accepted_by_user_id`, never one without the other)."""
    candidates = [
        invitation
        for invitation in list_invitations_for_tenant(tenant_id)
        if invitation.accepted_by_user_id == accepting_user_id
    ]
    if not candidates:
        return None

    def _accepted_at(invitation: Invitation) -> datetime:
        # Guaranteed non-None for every `candidates` entry -- see this
        # function's own docstring -- `Invitation.accepted_at`'s static
        # type is merely wider than what the CHECK constraint enforces.
        assert invitation.accepted_at is not None
        return invitation.accepted_at

    return max(candidates, key=_accepted_at).inviter_user_id


def assign_starting_client_role(
    actor_user_id: uuid.UUID, client_tenant_id: uuid.UUID, membership_id: uuid.UUID
) -> MembershipRole:
    """Grant a newly-accepted client member their baseline `"member"`
    role (`docs/ROADMAP.md` Phase 3.2's own "land in their own tenant
    with the correct starting role" acceptance criterion). The role
    currently grants no permissions (`product/agency/roles.py`'s own
    docstring: Phase 3 has no business-domain permission to grant yet) --
    this is a deliberate placeholder anchor for Phase 4+, not an
    oversight.

    `actor_user_id` needs `(resource="membership_role", action="create")`
    authority at `client_tenant_id` -- ordinarily the inviting agency
    owner, via the same `SUBTREE` reach `invite_client_member()` above
    relies on; `core.rbac.assign_role()` enforces this itself (and its
    own anti-amplification check), this function adds nothing extra.
    """
    role = ensure_client_member_role(client_tenant_id)
    return assign_role(
        client_tenant_id,
        membership_id,
        role.id,
        scope=RoleScope.SELF,
        actor_user_id=actor_user_id,
    )
