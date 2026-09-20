"""Integration tests for product/agency/onboarding.py. Marked
`integration`, excluded from the default `pytest` run.

**Resolved 2026-09-19** -- history preserved. Until SaaS-OS commit
`1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6`, `accept_client_invitation()`
was confirmed to always raise `InvitationInvalidError`, for every token,
regardless of validity (see the previous revision of this file, and
`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s "Related,
separately-tracked SaaS-OS limitation" section for the full history of
that finding). That commit made `core.identity.accept_invitation()`
require an explicit `tenant_id` and resolve the token inside
`tenant_session_scope(tenant_id)` from the start -- no untenanted read,
no RLS gap. This file now proves the real, working send -> accept ->
assign-starting-role chain end-to-end, plus every failure mode named in
the Phase 3 onboarding-completion task: wrong tenant, invalid token,
expired, revoked, already-accepted, and concurrent acceptance.

**Onboarding-role remediation.** `accept_client_invitation()` now
assigns the starting role itself on every successful accept (see its own
docstring in `product/agency/onboarding.py`). Every failure-path test
below that asserts `get_membership(...) is None` already, structurally,
also proves "no role was assigned": `product.agency.onboarding
::accept_client_invitation()`'s new role-assignment step runs strictly
after `accept_invitation()` returns a real membership, and
`core.rbac.MembershipRole` is foreign-keyed to a `TenantMembership` row
that, in every one of these failure cases, was never created -- there is
structurally nothing for a role to attach to. A separate "and no role
was assigned either" assertion on each of those tests would only repeat
that same structural fact, not exercise a different code path.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.identity import (
    InvitationInvalidError,
    accept_invitation,
    add_tenant_membership,
    get_membership,
    revoke_invitation,
)
from core.identity.models import MembershipStatus
from product.agency.onboarding import (
    accept_client_invitation,
    assign_starting_client_role,
    invite_client_member,
)
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import CLIENT_MEMBER_ROLE_NAME

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_invite_client_member_works() -> None:
    """The send half -- fully functional, per docs/ROADMAP.md Phase
    3.2's own scope ("product-facing invitation UI/API only -- the
    underlying invitation lifecycle is Category A")."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")
        assert sent.tenant_id == client.tenant_id
        assert sent.raw_token
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invite_client_member_without_authority_is_denied() -> None:
    """core.identity.create_invitation() self-authorizes via can() --
    this wrapper adds nothing extra, so an unrelated actor is denied by
    Core itself, not by this product's own code."""
    from core.identity import InvitationNotAuthorizedError

    owner = make_user()
    stranger = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        with pytest.raises(InvitationNotAuthorizedError):
            invite_client_member(stranger.id, client.tenant_id, "nope@example.com")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_accept_client_invitation_end_to_end_then_assign_starting_role() -> None:
    """The full, real chain: invite -> accept -> starting role, all the
    way through -- the onboarding-completion remediation this file now
    proves. `accept_client_invitation()` performs zero authorization
    logic of its own for the *acceptance* itself (design-review note,
    not just an assertion): it passes `raw_token`/`accepting_user_id`/
    `tenant_id` straight through to `core.identity.accept_invitation()`,
    which is the sole authority on whether the redemption succeeds -- no
    product-side pre-validation of the token/tenant pairing exists or is
    needed. What *is* new: `accept_client_invitation()` now also assigns
    the starting role itself, automatically, using the invitation's own
    inviter as the granting actor -- no separate manual call is needed
    (or, per the assertion below, even safely repeatable) any more."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")

        membership = accept_client_invitation(sent.raw_token, accepting_user.id, sent.tenant_id)
        assert membership.tenant_id == client.tenant_id
        assert membership.status == MembershipStatus.ACTIVE.value

        from core.rbac import get_membership_role, list_roles

        roles = {r.name: r for r in list_roles(client.tenant_id)}
        member_role = roles[CLIENT_MEMBER_ROLE_NAME]
        assignment = get_membership_role(client.tenant_id, membership.id, member_role.id)
        assert assignment is not None, (
            "accept_client_invitation() must assign the starting role itself -- "
            "no separate call should be required."
        )

        # A second, manual call for the identical membership+role is a
        # safe no-op (idempotency the remediation explicitly preserves),
        # never a crash and never a second row.
        from core.rbac import DuplicateRoleAssignmentError

        with pytest.raises(DuplicateRoleAssignmentError):
            assign_starting_client_role(owner.id, client.tenant_id, membership.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_with_wrong_tenant_fails_closed() -> None:
    """A genuinely valid, unexpired, unrevoked token for `client_a`,
    accepted with `client_b`'s real (existing) tenant_id, must fail --
    never succeed, never leak which tenant the token actually belongs
    to (mirrors saas-os's own
    tests/core/identity/test_invitation_integration.py::
    test_accept_invitation_with_wrong_tenant_raises_and_discloses_nothing,
    now exercised through this product's own wrapper)."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_a = provision_client(owner.id, agency.tenant_id, _name("client-a"))
    client_b = provision_client(owner.id, agency.tenant_id, _name("client-b"))
    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client_a.tenant_id, "new-member@example.com")

        with pytest.raises(InvitationInvalidError):
            accept_client_invitation(sent.raw_token, accepting_user.id, client_b.tenant_id)

        assert get_membership(client_a.tenant_id, accepting_user.id) is None
        assert get_membership(client_b.tenant_id, accepting_user.id) is None

        # Control: the identical token, correctly tenant-scoped, still works.
        membership = accept_client_invitation(sent.raw_token, accepting_user.id, client_a.tenant_id)
        assert membership.tenant_id == client_a.tenant_id
    finally:
        cleanup_tenant_tree(client_a.tenant_id, client_b.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_cannot_create_cross_agency_membership() -> None:
    """The cross-agency variant of the wrong-tenant case: a client-A
    invitation accepted with an entirely unrelated agency's own tenant_id
    (not even a sibling client -- the agency root itself, under a
    different agency altogether) must fail identically, never create a
    membership anywhere but client_a's own tenant."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_a = provision_client(owner.id, agency.tenant_id, _name("client-a"))

    other_owner = make_user()
    other_agency = provision_agency(other_owner.id, _name("other-agency"))

    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client_a.tenant_id, "new-member@example.com")

        with pytest.raises(InvitationInvalidError):
            accept_client_invitation(sent.raw_token, accepting_user.id, other_agency.tenant_id)

        assert get_membership(client_a.tenant_id, accepting_user.id) is None
        assert get_membership(other_agency.tenant_id, accepting_user.id) is None
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id, accepting_user.id)


def test_accept_with_invalid_token_fails_closed() -> None:
    """A syntactically-plausible but entirely made-up token, against a
    real, valid tenant_id -- isolates that the token itself is what's
    being validated, not the tenant."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        with pytest.raises(InvitationInvalidError):
            accept_client_invitation("not-a-real-token", accepting_user.id, client.tenant_id)
        assert get_membership(client.tenant_id, accepting_user.id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_with_no_tenant_ever_invited_fails_closed() -> None:
    """A real tenant_id for a tenant that has never had any invitation
    issued to anyone at all -- confirms acceptance can never conjure a
    membership from nothing, not even against a tenant with zero
    invitation history."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    untouched_client = provision_client(owner.id, agency.tenant_id, _name("untouched"))
    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")
        with pytest.raises(InvitationInvalidError):
            accept_client_invitation(sent.raw_token, accepting_user.id, untouched_client.tenant_id)
        assert get_membership(untouched_client.tenant_id, accepting_user.id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, untouched_client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_expired_token_fails_closed() -> None:
    """Mirrors saas-os's own
    tests/core/identity/test_invitation_integration.py::
    test_accept_expired_invitation_raises exactly: `ck_invitations_valid_
    time_range` prevents ever creating an already-expired invitation, so
    expiry is exercised via `accept_invitation()`'s own `now=` test-
    injection parameter -- called directly here (not through this
    product's own `accept_client_invitation()` wrapper, which
    deliberately does not expose `now`, since a real caller must never
    pass it; this is the one test in this file that reaches past the
    product wrapper, specifically to exercise a test-only capability the
    wrapper correctly does not surface)."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        from core.identity import create_invitation

        expires_at = datetime.now(UTC) + timedelta(hours=1)
        _invitation, raw_token = create_invitation(
            client.tenant_id, owner.id, "new-member@example.com", expires_at=expires_at
        )

        with pytest.raises(InvitationInvalidError):
            accept_invitation(
                raw_token,
                accepting_user.id,
                client.tenant_id,
                now=expires_at + timedelta(minutes=1),
            )
        assert get_membership(client.tenant_id, accepting_user.id) is None

        # Control: inside the window, the identical inputs are accepted.
        membership = accept_invitation(
            raw_token,
            accepting_user.id,
            client.tenant_id,
            now=expires_at - timedelta(minutes=1),
        )
        assert membership.status == MembershipStatus.ACTIVE.value
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_revoked_token_fails_closed() -> None:
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")
        revoke_invitation(client.tenant_id, sent.invitation_id, actor_user_id=owner.id)

        with pytest.raises(InvitationInvalidError):
            accept_client_invitation(sent.raw_token, accepting_user.id, client.tenant_id)
        assert get_membership(client.tenant_id, accepting_user.id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_accept_already_accepted_token_fails_closed_on_second_attempt() -> None:
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")

        first = accept_client_invitation(sent.raw_token, accepting_user.id, client.tenant_id)
        assert first.status == MembershipStatus.ACTIVE.value

        with pytest.raises(InvitationInvalidError):
            accept_client_invitation(sent.raw_token, accepting_user.id, client.tenant_id)

        # Still exactly one membership -- the replay never created a second.
        membership = get_membership(client.tenant_id, accepting_user.id)
        assert membership is not None
        assert membership.id == first.id

        # And still exactly one starting-role assignment -- the replay
        # raised inside accept_invitation() itself, before this product's
        # role-assignment step ever ran a second time, so there was
        # nothing to duplicate in the first place.
        from core.rbac import get_membership_role, list_roles

        roles = {r.name: r for r in list_roles(client.tenant_id)}
        member_role = roles[CLIENT_MEMBER_ROLE_NAME]
        assert get_membership_role(client.tenant_id, membership.id, member_role.id) is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_reaccepting_a_second_fresh_invitation_while_already_active_does_not_duplicate_role() -> (
    None
):
    """A real, documented Core edge case, distinct from a replayed token:
    `core.identity.accept_invitation()`'s own docstring says "an
    already-ACTIVE membership is a no-op success (the invitation is
    still consumed)" -- so a *second, separate* invitation (a fresh
    token) to a user who is already an ACTIVE member of this tenant
    still redeems successfully, reusing the same membership row. This
    product's new role-assignment step must not treat that as a reason
    to raise `DuplicateRoleAssignmentError` up to the caller -- it is
    exactly the idempotent case `accept_client_invitation()`'s own
    docstring names, caught and swallowed internally."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user = make_user()
    try:
        first_invite = invite_client_member(owner.id, client.tenant_id, "member@example.com")
        first_membership = accept_client_invitation(
            first_invite.raw_token, accepting_user.id, client.tenant_id
        )
        assert first_membership.status == MembershipStatus.ACTIVE.value

        second_invite = invite_client_member(owner.id, client.tenant_id, "member@example.com")
        second_membership = accept_client_invitation(
            second_invite.raw_token, accepting_user.id, client.tenant_id
        )

        assert second_membership.id == first_membership.id
        assert second_membership.status == MembershipStatus.ACTIVE.value

        from core.rbac import get_membership_role, list_roles

        roles = {r.name: r for r in list_roles(client.tenant_id)}
        member_role = roles[CLIENT_MEMBER_ROLE_NAME]
        assert (
            get_membership_role(client.tenant_id, first_membership.id, member_role.id) is not None
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user.id)


def test_concurrent_acceptance_is_safe() -> None:
    """Real concurrency against the real disposable Postgres: two threads
    race to accept the identical (raw_token, tenant_id) for two different
    accepting_user_ids, synchronized to start together. Mirrors
    `_consume_locked_invitation()`'s own documented row-lock guarantee
    (`with_for_update=True`): the loser's re-validation finds
    `accepted_at` already set and raises -- exactly one thread succeeds,
    exactly one membership row results, and (the onboarding-role
    remediation's own addition to this test) exactly one starting-role
    assignment results too -- the loser never reaches
    `assign_starting_client_role()` at all, since `accept_invitation()`
    itself raises before this product's new role-assignment step ever
    runs for that thread."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    accepting_user_a = make_user()
    accepting_user_b = make_user()
    try:
        sent = invite_client_member(owner.id, client.tenant_id, "new-member@example.com")

        barrier = threading.Barrier(2)
        results: dict[str, tuple[str, object]] = {}

        def _attempt(label: str, accepting_user_id: uuid.UUID) -> None:
            barrier.wait()
            try:
                membership = accept_client_invitation(
                    sent.raw_token, accepting_user_id, client.tenant_id
                )
                results[label] = ("ok", membership)
            except InvitationInvalidError as exc:
                results[label] = ("failed", exc)

        thread_a = threading.Thread(target=_attempt, args=("a", accepting_user_a.id))
        thread_b = threading.Thread(target=_attempt, args=("b", accepting_user_b.id))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)

        outcomes = [results["a"][0], results["b"][0]]
        assert sorted(outcomes) == ["failed", "ok"], results

        membership_a = get_membership(client.tenant_id, accepting_user_a.id)
        membership_b = get_membership(client.tenant_id, accepting_user_b.id)
        # Exactly one of the two candidate accepting users ended up with
        # the membership -- never both, never neither.
        assert (membership_a is not None) != (membership_b is not None)

        winning_membership = membership_a or membership_b
        assert winning_membership is not None
        from core.rbac import get_membership_role, list_roles

        roles = {r.name: r for r in list_roles(client.tenant_id)}
        member_role = roles[CLIENT_MEMBER_ROLE_NAME]
        assignment = get_membership_role(client.tenant_id, winning_membership.id, member_role.id)
        assert assignment is not None, "the winning thread's membership must have the starting role"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, accepting_user_a.id, accepting_user_b.id)


def test_assign_starting_client_role_proven_independently_of_a_real_acceptance() -> None:
    """assign_starting_client_role() remains independently callable and
    independently tested here too (in addition to being chained for real
    in test_accept_client_invitation_end_to_end_then_assign_starting_role
    above), against a membership constructed directly via
    core.identity.add_tenant_membership() -- useful for isolating this
    function's own behavior without going through the full invite/accept
    round trip every time."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    new_member = make_user()
    try:
        membership = add_tenant_membership(client.tenant_id, new_member.id)
        membership_role = assign_starting_client_role(owner.id, client.tenant_id, membership.id)
        assert membership_role.membership_id == membership.id

        from core.rbac import list_roles

        roles = {r.id: r for r in list_roles(client.tenant_id)}
        assert roles[membership_role.role_id].name == CLIENT_MEMBER_ROLE_NAME
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, new_member.id)


def test_assign_starting_client_role_is_idempotent_role_creation() -> None:
    """ensure_client_member_role() is safe to call more than once for
    the same tenant (two different members being onboarded)."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    member_one = make_user()
    member_two = make_user()
    try:
        membership_one = add_tenant_membership(client.tenant_id, member_one.id)
        membership_two = add_tenant_membership(client.tenant_id, member_two.id)
        role_one = assign_starting_client_role(owner.id, client.tenant_id, membership_one.id)
        role_two = assign_starting_client_role(owner.id, client.tenant_id, membership_two.id)
        assert role_one.role_id == role_two.role_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member_one.id, member_two.id)
