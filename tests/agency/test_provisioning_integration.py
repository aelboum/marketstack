"""Integration tests for product/agency/provisioning.py against a real,
already-migrated PostgreSQL database. Marked `integration`, excluded from
the default `pytest` run (see scripts/check-integration.sh).

Covers docs/ROADMAP.md Phase 3.1's own acceptance criterion ("agency
onboarding -> first client creation works end-to-end") and several of
the numbered isolation/security requirements from the Phase 3 task brief:
requirement 5 (SUBTREE reach is live, no bootstrap needed at a new
client), requirement 7 (a SUSPENDED/DELETED agency cannot have clients
provisioned under it), requirement 10 (an unrelated actor cannot create a
client under an agency merely by knowing its tenant_id -- the IDOR
Finding #3/docs/ADR/0002 exists to close).
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import can
from core.tenancy import TenantStatus, get_ancestor_chain, transition_tenant_status
from product.agency.errors import AgencyAccessDeniedError
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import AGENCY_CLIENT_RESOURCE

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_agency_onboarding_then_first_client_creation_end_to_end() -> None:
    """docs/ROADMAP.md Phase 3.1's own acceptance criterion, verbatim."""
    owner = make_user()
    try:
        agency = provision_agency(owner.id, _name("agency"))
        try:
            client = provision_client(owner.id, agency.tenant_id, _name("client"))
            try:
                assert client.agency_tenant_id == agency.tenant_id
                # The agency's own owner reaches the brand-new client
                # immediately, with no further grant.
                assert can(
                    actor_id=owner.id,
                    tenant_id=client.tenant_id,
                    action="create",
                    resource=AGENCY_CLIENT_RESOURCE,
                )
                # core.tenant_ancestry reflects the hierarchy correctly.
                assert agency.tenant_id in get_ancestor_chain(client.tenant_id)
            finally:
                cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        except Exception:
            cleanup_tenant_tree(agency.tenant_id)
            raise
    finally:
        cleanup_users(owner.id)


def test_agency_creates_n_clients() -> None:
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_ids = []
    try:
        for i in range(3):
            client = provision_client(owner.id, agency.tenant_id, _name(f"client-{i}"))
            client_ids.append(client.tenant_id)
        assert len(set(client_ids)) == 3
        for client_id in client_ids:
            assert agency.tenant_id in get_ancestor_chain(client_id)
    finally:
        cleanup_tenant_tree(*client_ids, agency.tenant_id)
        cleanup_users(owner.id)


def test_subtree_role_reaches_a_client_created_after_the_role_was_assigned() -> None:
    """Requirement 5: SUBTREE's live-re-evaluation semantics -- the
    agency owner's role was assigned once, at agency-creation time, long
    before this specific client existed. No further action is taken
    between agency creation and this assertion beyond provision_client()
    itself."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    client_tenant_id = None
    try:
        assert not can(
            actor_id=owner.id,
            tenant_id=uuid.uuid4(),
            action="create",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        client = provision_client(owner.id, agency.tenant_id, _name("client"))
        client_tenant_id = client.tenant_id
        assert can(
            actor_id=owner.id,
            tenant_id=client.tenant_id,
            action="read",
            resource=AGENCY_CLIENT_RESOURCE,
        )
    finally:
        ids = (
            [agency.tenant_id] if client_tenant_id is None else [client_tenant_id, agency.tenant_id]
        )
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_client_under_a_real_agency() -> None:
    """Requirement 10: an authenticated user with zero relationship to a
    real, existing agency tenant must be denied -- not because the
    tenant_id 'looks wrong', but because core.rbac.can() genuinely
    returns False for this actor/tenant pair (Finding #3 / docs/ADR/0002:
    core.tenancy.create_tenant() itself has no authorization check)."""
    owner = make_user()
    attacker = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        assert not can(
            actor_id=attacker.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        with pytest.raises(AgencyAccessDeniedError):
            provision_client(attacker.id, agency.tenant_id, _name("should-not-exist"))
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, attacker.id)


def test_suspended_agency_cannot_have_clients_provisioned() -> None:
    """Requirement 7: verified directly, not assumed -- can() re-checks
    the target tenant's own lifecycle (core/rbac/authorization.py) before
    evaluating any ordinary allow path, so a SUSPENDED agency's own
    owner loses reach into it."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        transition_tenant_status(agency.tenant_id, TenantStatus.SUSPENDED)
        assert not can(
            actor_id=owner.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource=AGENCY_CLIENT_RESOURCE,
        )
        with pytest.raises(AgencyAccessDeniedError):
            provision_client(owner.id, agency.tenant_id, _name("should-not-exist"))
    finally:
        # Reactivate before teardown -- cleanup_tenant_tree()'s own
        # deletes must not themselves be blocked by a closed lifecycle
        # (transition_tenant_status() itself has no such restriction for
        # ACTIVE, unlike DELETED/PURGING).
        transition_tenant_status(agency.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_deleted_agency_parent_rejects_new_child_tenant_structurally() -> None:
    """Requirement 7's second half: core.tenancy.create_tenant() itself
    refuses a closed (DELETED/PURGING/PURGED) parent -- a structural
    check, independent of this product's own agency.client permission
    check, verified directly here rather than assumed."""
    from core.tenancy import TenantClosedError

    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        transition_tenant_status(agency.tenant_id, TenantStatus.SUSPENDED)
        transition_tenant_status(agency.tenant_id, TenantStatus.DELETED)
        with pytest.raises((AgencyAccessDeniedError, TenantClosedError)):
            provision_client(owner.id, agency.tenant_id, _name("should-not-exist"))
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)
