"""Adversarial cross-agency/cross-client isolation tests -- the largest
and most important part of the Phase 3 task brief's own test
requirements. Marked `integration`, excluded from the default `pytest`
run.

Maps directly onto the 10 numbered isolation/security requirements in
the Phase 3 implementation brief:

    1. Agency A cannot access Agency B's clients.
    2. A client cannot access another unrelated client's data.
    3. An agency can access only the clients it is authorized to manage.
    4. Explicit deny overrides an otherwise-reaching SUBTREE role.
    6. Cross-agency identifiers cannot be used to bypass authorization.

(5, 7, 10 are covered in test_provisioning_integration.py; 8 is
satisfied by construction -- see docs/ADR/0003-...,  this phase adds no
new table; 9 is a design review, not a runtime test -- see the Phase 3
implementation report.)
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import RoleScope, can
from product.agency.delegation import create_client_deny
from product.agency.errors import AgencyAccessDeniedError
from product.agency.provisioning import list_clients, provision_agency, provision_client
from product.agency.roles import AGENCY_CLIENT_RESOURCE

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_agency_subtree_delegation(delegator_id, delegate_id, agency_tenant_id):
    """Delegate at the AGENCY tenant, SUBTREE-scoped -- the only
    delegation shape an agency owner (who holds no *direct* membership
    at any client, by this product's own Phase 3.1 design) can actually
    create, per `core.rbac.service._actor_reaches_tenant_at_scope()`'s
    real behavior (found empirically -- see
    tests/agency/test_delegation_integration.py
    ::test_delegation_create_and_revoke_round_trip's own docstring for
    the full explanation). A SELF-scoped delegation targeted directly at
    a client tenant is NOT authorized for this actor, despite `can()`
    itself clearly authorizing them there via SUBTREE."""
    from product.agency.delegation import create_client_delegation

    return create_client_delegation(
        delegator_user_id=delegator_id,
        delegate_user_id=delegate_id,
        tenant_id=agency_tenant_id,
        resource=AGENCY_CLIENT_RESOURCE,
        action="read",
        scope_mode=RoleScope.SUBTREE,
    )


def test_agency_cannot_access_another_agencys_clients() -> None:
    """Requirements 1 and 3: Agency A's owner has zero reach into Agency
    B's client, and list_clients() for Agency B (called by Agency A's
    owner) is denied at the service layer, not merely empty."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    client_b = provision_client(owner_b.id, agency_b.tenant_id, _name("client-b"))
    try:
        assert not can(
            actor_id=owner_a.id,
            tenant_id=client_b.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        assert not can(
            actor_id=owner_a.id,
            tenant_id=agency_b.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        with pytest.raises(AgencyAccessDeniedError):
            list_clients(owner_a.id, agency_b.tenant_id)
        # Agency A can still list its own (empty) client set -- proves
        # the denial above is about Agency B specifically, not a global
        # break in list_clients() itself.
        assert list_clients(owner_a.id, agency_a.tenant_id) == []
    finally:
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_client_cannot_access_unrelated_client_data() -> None:
    """Requirement 2: a client A member has no membership, no SUBTREE
    reach, and no delegation into client B -- can() is False for any
    permission there."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    client_a = provision_client(owner_a.id, agency_a.tenant_id, _name("client-a"))
    client_b = provision_client(owner_b.id, agency_b.tenant_id, _name("client-b"))
    client_a_member = make_user()
    try:
        from core.identity import add_tenant_membership

        add_tenant_membership(client_a.tenant_id, client_a_member.id)
        assert not can(
            actor_id=client_a_member.id,
            tenant_id=client_b.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        assert not can(
            actor_id=client_a_member.id,
            tenant_id=client_b.tenant_id,
            action="create",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id, client_a_member.id)


def test_cross_agency_real_but_unrelated_tenant_id_never_authorizes() -> None:
    """Requirement 6: the supplied tenant_id is real, existing, and
    syntactically perfect -- it is simply not one this actor has any
    relationship to. Denial must come from can() genuinely evaluating
    false, not from a shape/format check."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    try:
        # agency_b.tenant_id is a real, existing tenant -- owner_a simply
        # has no role/delegation/membership reaching it.
        assert not can(
            actor_id=owner_a.id,
            tenant_id=agency_b.tenant_id,
            action="create",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        with pytest.raises(AgencyAccessDeniedError):
            provision_client(owner_a.id, agency_b.tenant_id, _name("should-not-exist"))
    finally:
        cleanup_tenant_tree(agency_a.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_explicit_deny_overrides_subtree_delegation() -> None:
    """Requirement 4, mirroring saas-os's own
    examples/reference-consumer/reference_consumer/scenarios.py
    ::deny_widget_access() /
    tests/test_reference_consumer_scenarios_integration.py's deny-
    overrides-SUBTREE shape, adapted to this product's own
    `agency.client` permission: a second agency staff member,
    deliberately given no role of their own (mirrors reference-
    consumer's own "business_support_user... deliberately given NO role"
    comment), reaches every client only via an agency-tenant-level,
    SUBTREE-scoped delegation from the agency owner (see
    `_create_agency_subtree_delegation()`'s own docstring for why it
    must be shaped this way); an explicit deny at one specific client
    removes it there, and only there."""
    owner = make_user()
    staff = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_one = provision_client(owner.id, agency.tenant_id, _name("client-one"))
    client_two = provision_client(owner.id, agency.tenant_id, _name("client-two"))
    try:
        _create_agency_subtree_delegation(owner.id, staff.id, agency.tenant_id)
        # The SUBTREE delegation reaches both clients uniformly before
        # any deny exists.
        assert can(
            actor_id=staff.id,
            tenant_id=client_one.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        assert can(
            actor_id=staff.id,
            tenant_id=client_two.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )

        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=staff.id,
            tenant_id=client_one.tenant_id,
            resource=AGENCY_CLIENT_RESOURCE,
            action="read",
            scope_mode=RoleScope.SELF,
        )

        # The deny overrides the delegation immediately.
        assert not can(
            actor_id=staff.id,
            tenant_id=client_one.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        # The owner's own SUBTREE reach into client_one is unaffected --
        # the deny targets staff specifically, never the owner.
        assert can(
            actor_id=owner.id,
            tenant_id=client_one.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        # client_two remains unaffected by a deny scoped to client_one --
        # staff's SUBTREE delegation still reaches it.
        assert can(
            actor_id=staff.id,
            tenant_id=client_two.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(client_one.tenant_id, client_two.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, staff.id)
