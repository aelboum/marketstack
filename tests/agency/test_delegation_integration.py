"""Integration tests for product/agency/delegation.py. Marked
`integration`, excluded from the default `pytest` run.

The cross-agency SUBTREE/deny scenario itself is covered in
tests/agency/test_isolation_integration.py -- this file covers this
module's own added behavior: the "only an already-registered permission
may be delegated/denied" guard, and ordinary create/revoke round-trips.
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import RoleScope, can
from product.agency.delegation import (
    create_client_delegation,
    create_client_deny,
    revoke_client_delegation,
    revoke_client_deny,
)
from product.agency.errors import UnknownDelegatablePermissionError
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import AGENCY_CLIENT_RESOURCE

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_unknown_permission_cannot_be_delegated() -> None:
    """A delegator may only name a (resource, action) pair that is
    already a real, registered core.rbac permission -- never conjure a
    new one through this endpoint (module docstring's mass-assignment-
    adjacent risk)."""
    owner = make_user()
    delegate = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        with pytest.raises(UnknownDelegatablePermissionError):
            create_client_delegation(
                delegator_user_id=owner.id,
                delegate_user_id=delegate.id,
                tenant_id=agency.tenant_id,
                resource="totally.made.up",
                action="do-anything",
            )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, delegate.id)


def test_unknown_permission_cannot_be_denied() -> None:
    owner = make_user()
    principal = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        with pytest.raises(UnknownDelegatablePermissionError):
            create_client_deny(
                grantor_user_id=owner.id,
                principal_user_id=principal.id,
                tenant_id=agency.tenant_id,
                resource="totally.made.up",
                action="do-anything",
            )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, principal.id)


def test_delegation_create_and_revoke_round_trip() -> None:
    """**Resolved 2026-09-19** -- history preserved, read before changing
    the `tenant_id`/`scope_mode` here. `core.rbac.service
    ._actor_reaches_tenant_at_scope()` (the anti-amplification check
    `create_delegation()` runs) used to check ONLY a *direct*
    `TenantMembership` + role at its own `tenant_id` argument for a
    `SELF`-scope check -- unlike `can()`, it did NOT walk ancestors,
    despite its own docstring's "equivalent to plain can() at tenant_id"
    claim. That meant an agency owner (no direct membership at any
    client, by this product's own deliberate Phase 3.1 design -- see
    product/agency/provisioning.py) could NOT create a `SELF`-scoped
    delegation targeted at a specific *client* tenant, even though
    `can()` clearly authorized the owner there.

    SaaS-OS commit `1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6` fixed this
    (the `SELF` branch now walks ancestors for a `SUBTREE` role too,
    matching `can()`) -- see `test_self_scoped_delegation_at_a_client_
    via_inherited_subtree_reach` below for that now-working case,
    proven with zero product-side code changes. This test itself keeps
    exercising the `SUBTREE`-at-the-agency shape, which was always
    correct and remains a fully valid, distinct pattern (delegating once
    at the agency, reaching every current and future client) --
    `docs/ADR/0002-...`'s own "Resolved" note has the full history. See
    tests/agency/test_isolation_integration.py's own deny-override test
    for the complementary case (create_deny() has no anti-amplification
    constraint at all -- it can target a specific client directly and
    always could)."""
    owner = make_user()
    delegate = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        grant = create_client_delegation(
            delegator_user_id=owner.id,
            delegate_user_id=delegate.id,
            tenant_id=agency.tenant_id,
            resource=AGENCY_CLIENT_RESOURCE,
            action="read",
            scope_mode=RoleScope.SUBTREE,
        )
        assert can(
            actor_id=delegate.id,
            tenant_id=agency.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        # SUBTREE-mode delegation reaches the client too, the same live
        # re-evaluation property an ordinary SUBTREE role has.
        assert can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )

        revoke_client_delegation(
            revoker_user_id=owner.id, tenant_id=agency.tenant_id, delegation_grant_id=grant.id
        )
        assert not can(
            actor_id=delegate.id,
            tenant_id=agency.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        assert not can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, delegate.id)


def test_self_scoped_delegation_at_a_client_via_inherited_subtree_reach() -> None:
    """Proves the SaaS-OS fix (commit `1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6`)
    from this product's own side, with completely unchanged product code
    (`product/agency/delegation.py` already passed `tenant_id`/
    `scope_mode` straight through to `core.rbac.create_delegation()` --
    see this file's own history note on `test_delegation_create_and_
    revoke_round_trip` above). The agency owner here has ONLY inherited
    `SUBTREE` reach into `client` -- no direct membership there at all
    (the exact Phase 3.1 shape) -- and can now create a `SELF`-scoped
    delegation targeted directly at `client`, which `can()` already said
    they were authorized for."""
    owner = make_user()
    delegate = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        assert can(
            actor_id=owner.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )

        grant = create_client_delegation(
            delegator_user_id=owner.id,
            delegate_user_id=delegate.id,
            tenant_id=client.tenant_id,
            resource=AGENCY_CLIENT_RESOURCE,
            action="read",
            scope_mode=RoleScope.SELF,
        )
        assert can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        # SELF-mode: the delegate's reach is exactly the one client, never
        # the agency itself or any sibling client.
        assert not can(
            actor_id=delegate.id,
            tenant_id=agency.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )

        revoke_client_delegation(
            revoker_user_id=owner.id, tenant_id=client.tenant_id, delegation_grant_id=grant.id
        )
        assert not can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, delegate.id)


def test_deny_create_and_revoke_round_trip() -> None:
    """`create_deny()` has no anti-amplification check of its own kind
    (module docstring: "a deny can only remove authority") -- so, unlike
    delegation above, the owner's SUBTREE reach into a specific client
    is enough to deny someone there directly, no agency-tenant-level
    workaround needed."""
    owner = make_user()
    delegate = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        create_client_delegation(
            delegator_user_id=owner.id,
            delegate_user_id=delegate.id,
            tenant_id=agency.tenant_id,
            resource=AGENCY_CLIENT_RESOURCE,
            action="read",
            scope_mode=RoleScope.SUBTREE,
        )
        deny = create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=delegate.id,
            tenant_id=client.tenant_id,
            resource=AGENCY_CLIENT_RESOURCE,
            action="read",
        )
        assert not can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        # The deny is scoped to the client only -- the agency-level
        # SUBTREE delegation itself is untouched.
        assert can(
            actor_id=delegate.id,
            tenant_id=agency.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )

        revoke_client_deny(
            revoker_user_id=owner.id, tenant_id=client.tenant_id, deny_grant_id=deny.id
        )
        assert can(
            actor_id=delegate.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, delegate.id)
