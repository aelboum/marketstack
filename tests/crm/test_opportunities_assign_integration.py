"""`product/crm/opportunities.py::assign_opportunity()` (docs/ROADMAP.md
Phase 22, scope item (c)). Real disposable Postgres. Marked `integration`,
excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError
from product.crm.opportunities import assign_opportunity, create_opportunity
from product.crm.pipelines import create_pipeline, create_stage

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _opportunity(owner_id, tenant_id):
    pipeline = create_pipeline(owner_id, tenant_id, name="Sales", is_default=True)
    stage = create_stage(owner_id, tenant_id, pipeline.id, name="Open", position=0)
    return create_opportunity(
        owner_id, tenant_id, name=_name("deal"), pipeline_id=pipeline.id, stage_id=stage.id
    )


def test_assign_then_unassign_opportunity() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        opportunity = _opportunity(owner.id, client.tenant_id)

        assigned = assign_opportunity(owner.id, client.tenant_id, opportunity.id, member.id)
        assert assigned.assigned_user_id == member.id

        unassigned = assign_opportunity(owner.id, client.tenant_id, opportunity.id, None)
        assert unassigned.assigned_user_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_assign_to_a_non_member_is_rejected_non_enumerating() -> None:
    """The IDOR-adjacent check: a real, existing user with NO membership
    at this tenant must not be assignable -- and the failure must be the
    same non-enumerating `CrmReferenceNotFoundError` an unknown id would
    produce, never a distinguishing message."""
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        opportunity = _opportunity(owner.id, client.tenant_id)
        with pytest.raises(CrmReferenceNotFoundError):
            assign_opportunity(owner.id, client.tenant_id, opportunity.id, stranger.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_assign_to_an_unknown_user_id_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        opportunity = _opportunity(owner.id, client.tenant_id)
        with pytest.raises(CrmReferenceNotFoundError):
            assign_opportunity(owner.id, client.tenant_id, opportunity.id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_assign_unknown_opportunity_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(CrmReferenceNotFoundError):
            assign_opportunity(owner.id, client.tenant_id, uuid.uuid4(), owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_assign() -> None:
    owner = make_user()
    attacker = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        opportunity = _opportunity(owner.id, client.tenant_id)
        with pytest.raises(CrmAccessDeniedError):
            assign_opportunity(attacker.id, client.tenant_id, opportunity.id, owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, attacker.id)


def test_assignment_is_tenant_isolated() -> None:
    """A member of tenant B must not be assignable to an opportunity in
    tenant A, even though the actor performing the assignment (tenant A's
    own owner) is fully authorized on tenant A."""
    owner_a = make_user()
    owner_b = make_user()
    member_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _add_member(owner_b.id, client_b.tenant_id, member_b.id)
        opportunity = _opportunity(owner_a.id, client_a.tenant_id)
        with pytest.raises(CrmReferenceNotFoundError):
            assign_opportunity(owner_a.id, client_a.tenant_id, opportunity.id, member_b.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id, member_b.id)
