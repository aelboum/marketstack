"""Phone number provisioning + routing-target CRUD, isolation/authorization
(docs/ROADMAP.md Phase 8.1). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.telephony.errors import (
    TelephonyAccessDeniedError,
    TelephonyReferenceNotFoundError,
    TelephonyValidationError,
)
from product.telephony.numbers import (
    MAX_ROUTING_TARGETS,
    add_routing_target,
    get_phone_number,
    list_phone_numbers,
    list_routing_targets,
    provision_phone_number,
    release_phone_number,
)
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    """A real staff member of `tenant_id`, with the tenant's own
    provisioned `member` role -- not just a bare membership row, since
    `core.rbac.can()` (this module's own authorization chokepoint) is
    role-based. Mirrors the shape `product/agency/onboarding.py
    ::invite_client_member()`/`accept_client_invitation()` produce, done
    directly here (skipping the email-invitation flow, which is outside
    this test's own concern)."""
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id,
        membership.id,
        member_role.id,
        scope=RoleScope.SELF,
        actor_user_id=owner_id,
    )


def test_provision_get_list_release_phone_number() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        assert number.status == "active"

        fetched = get_phone_number(owner.id, client.tenant_id, number.id)
        assert fetched.id == number.id

        listed = list_phone_numbers(owner.id, client.tenant_id)
        assert any(n.id == number.id for n in listed)

        released = release_phone_number(owner.id, client.tenant_id, number.id)
        assert released.status == "released"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_phone_numbers_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        with pytest.raises(TelephonyReferenceNotFoundError):
            get_phone_number(other_owner.id, other_client.tenant_id, number.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_unrelated_actor_cannot_provision_a_number() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        with pytest.raises(TelephonyAccessDeniedError):
            provision_phone_number(
                unrelated.id, client.tenant_id, country_code="US", provider=provider
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_agency_owner_reaches_own_clients_phone_numbers_via_inherited_subtree() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        # The agency owner has no direct membership in the client tenant --
        # only inherited SUBTREE reach (docs/ADR/0002-...'s Phase 4
        # addendum) -- proving this works, not assumed.
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        assert number.tenant_id == client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_add_and_list_routing_targets_in_position_order() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    agent = make_user()
    _add_member(owner.id, client.tenant_id, agent.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        first = add_routing_target(owner.id, client.tenant_id, number.id, user_id=owner.id)
        second = add_routing_target(owner.id, client.tenant_id, number.id, user_id=agent.id)
        assert first.position == 0
        assert second.position == 1
        targets = list_routing_targets(owner.id, client.tenant_id, number.id)
        assert [t.user_id for t in targets] == [owner.id, agent.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, agent.id)


def test_routing_target_user_must_be_a_real_membership_in_this_tenant() -> None:
    """IDOR-adjacent check, mirrors
    tests/appointments/test_calendars_integration.py's own
    owner_user_id membership test."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated_user = make_user()
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        with pytest.raises(TelephonyReferenceNotFoundError):
            add_routing_target(owner.id, client.tenant_id, number.id, user_id=unrelated_user.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated_user.id)


def test_routing_target_for_unknown_phone_number_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(TelephonyReferenceNotFoundError):
            add_routing_target(owner.id, client.tenant_id, uuid.uuid4(), user_id=owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_routing_target_user_rejected_by_database_directly() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        add_routing_target(owner.id, client.tenant_id, number.id, user_id=owner.id)
        with pytest.raises(Exception):  # noqa: B017 -- real IntegrityError from the DB constraint
            add_routing_target(owner.id, client.tenant_id, number.id, user_id=owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_routing_target_list_bounded_at_max() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    users = [make_user() for _ in range(MAX_ROUTING_TARGETS)]
    for user in users:
        _add_member(owner.id, client.tenant_id, user.id)
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        for user in users:
            add_routing_target(owner.id, client.tenant_id, number.id, user_id=user.id)
        with pytest.raises(TelephonyValidationError):
            add_routing_target(owner.id, client.tenant_id, number.id, user_id=owner.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, *[u.id for u in users])
