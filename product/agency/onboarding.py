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
callable function -- now chained for real after a genuine acceptance in
the happy-path integration test, in addition to still being independently
testable on its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.identity import TenantMembership, accept_invitation, create_invitation
from core.rbac import MembershipRole, RoleScope, assign_role

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
    out of bounds."""
    return accept_invitation(raw_token, accepting_user_id, tenant_id)


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
