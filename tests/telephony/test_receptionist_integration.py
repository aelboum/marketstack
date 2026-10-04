"""`product/telephony/receptionist.py` -- AI receptionist actor
provisioning (docs/ROADMAP.md Phase 27.1). Real disposable Postgres.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.authority import SystemAuthority, SystemCaller
from core.identity import get_user
from core.rbac import can
from infra.db import session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.telephony.receptionist import (
    RECEPTIONIST_ROLE_NAME,
    ensure_ai_receptionist_actor,
)
from sqlalchemy import text

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _external_identity_count(user_id: uuid.UUID) -> int:
    with session_scope() as session:
        return session.execute(
            text("SELECT COUNT(*) FROM core.external_identities WHERE user_id = :id"),
            {"id": str(user_id)},
        ).scalar_one()


def _session_count(user_id: uuid.UUID) -> int:
    with session_scope() as session:
        return session.execute(
            text("SELECT COUNT(*) FROM core.sessions WHERE user_id = :id"), {"id": str(user_id)}
        ).scalar_one()


def test_first_provisioning_creates_the_actor() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        actor = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        assert actor.tenant_id == client.tenant_id
        assert get_user(actor.user_id) is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, actor.user_id)


def test_repeated_provisioning_is_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        first = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        second = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        assert second.user_id == first.user_id
        assert second.membership_id == first.membership_id
        assert second.role_id == first.role_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, first.user_id)


def test_actor_is_tenant_scoped_and_least_privilege() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        actor = ensure_ai_receptionist_actor(owner.id, client.tenant_id)

        # No owner/admin/cross-tenant privilege of any kind -- the role
        # was provisioned with zero permissions (module docstring).
        assert not can(
            actor_id=actor.user_id,
            tenant_id=client.tenant_id,
            action="create",
            resource="agency.client",
        )
        assert not can(
            actor_id=actor.user_id,
            tenant_id=client.tenant_id,
            action="create",
            resource="membership_role",
        )
        assert not can(
            actor_id=actor.user_id,
            tenant_id=client.tenant_id,
            action="read",
            resource="crm.contact",
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, actor.user_id)


def test_actor_cannot_access_another_tenant() -> None:
    owner_a, owner_b = make_user(), make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        actor = ensure_ai_receptionist_actor(owner_a.id, client_a.tenant_id)
        assert not can(
            actor_id=actor.user_id,
            tenant_id=client_b.tenant_id,
            action="read",
            resource="crm.contact",
        )
        # Even a permission the tenant-A role might later be granted must
        # never reach tenant B -- confirmed here against the one
        # capability tenant B's own owner definitely holds.
        assert not can(
            actor_id=actor.user_id,
            tenant_id=client_b.tenant_id,
            action="create",
            resource="agency.client",
        )
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id, actor.user_id)


def test_no_login_identity_or_session_is_ever_created() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        actor = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        assert _external_identity_count(actor.user_id) == 0
        assert _session_count(actor.user_id) == 0
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, actor.user_id)


def test_role_can_be_granted_permissions_later_by_a_future_phase() -> None:
    """Proves the role returned by provisioning is real and usable --
    Phase 27.2's own future grant_permission() calls against
    `actor.role_id` would take effect, without this phase inventing what
    those permissions are (module docstring's own "leave capability-
    specific grants to 27.2" design)."""
    from core.rbac import get_role, grant_permission, register_permission

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        actor = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        role = get_role(client.tenant_id, actor.role_id)
        assert role.name == RECEPTIONIST_ROLE_NAME

        permission = register_permission("crm.contact", "read")
        grant_permission(
            client.tenant_id,
            actor.role_id,
            permission.id,
            caller=SystemCaller(SystemAuthority.PROVISIONING),
        )
        assert can(
            actor_id=actor.user_id,
            tenant_id=client.tenant_id,
            action="read",
            resource="crm.contact",
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, actor.user_id)


def test_second_owner_assigning_role_reuses_authorization_boundary() -> None:
    """The assigning actor must already hold this tenant's own
    membership_role:create -- assign_role()'s own existing anti-
    amplification check, never re-implemented here. A stranger with no
    standing in the tenant cannot provision a receptionist for it."""
    from core.rbac.errors import RoleAssignmentNotAuthorizedError

    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(RoleAssignmentNotAuthorizedError):
            ensure_ai_receptionist_actor(stranger.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_second_provisioning_call_does_not_reassign_role_a_second_time() -> None:
    """A repeated ensure_ai_receptionist_actor() call must short-circuit
    before ever calling assign_role() again -- proven by having the
    *original* owner's own role assignment revoked from membership_role
    creation rights being irrelevant to the second call succeeding
    (idempotent lookup, no new assign_role() authorization check
    performed)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        first = ensure_ai_receptionist_actor(owner.id, client.tenant_id)
        # A second call using a stranger actor_user_id would fail loudly
        # if it ever tried to assign_role() again -- it must not, since
        # the receptionist already exists.
        stranger = make_user()
        second = ensure_ai_receptionist_actor(stranger.id, client.tenant_id)
        assert second.user_id == first.user_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id, first.user_id)
