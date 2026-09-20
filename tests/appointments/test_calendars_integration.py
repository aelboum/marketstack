"""Calendar CRUD, isolation/authorization, and owner_user_id membership
validation (docs/ROADMAP.md Phase 7.1). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import get_membership
from core.rbac import RoleScope
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.appointments.calendars import (
    create_calendar,
    delete_calendar,
    get_calendar,
    get_or_create_booking_link,
    list_calendars,
    update_calendar,
)
from product.appointments.errors import (
    AppointmentAccessDeniedError,
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.permissions import CALENDAR_RESOURCE

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_calendar_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id,
            client.tenant_id,
            name="Sales Calendar",
            owner_user_id=owner.id,
            timezone="Europe/Amsterdam",
        )
        assert calendar.timezone == "Europe/Amsterdam"

        fetched = get_calendar(owner.id, client.tenant_id, calendar.id)
        assert fetched.id == calendar.id

        listed = list_calendars(owner.id, client.tenant_id)
        assert any(c.id == calendar.id for c in listed)

        updated = update_calendar(owner.id, client.tenant_id, calendar.id, name="Renamed")
        assert updated.name == "Renamed"

        delete_calendar(owner.id, client.tenant_id, calendar.id)
        with pytest.raises(AppointmentReferenceNotFoundError):
            get_calendar(owner.id, client.tenant_id, calendar.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_timezone_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AppointmentValidationError):
            create_calendar(
                owner.id,
                client.tenant_id,
                name="Bad TZ",
                owner_user_id=owner.id,
                timezone="Not/A_Real_Zone",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_owner_user_id_must_be_a_real_membership_in_this_tenant() -> None:
    """IDOR-adjacent check: a syntactically-valid user id with no
    membership in this tenant must be rejected, not silently accepted as
    a calendar owner -- mirrors
    tests/conversations/test_threads_integration.py's own
    assign_thread()/get_membership() check."""
    owner = make_user()
    unrelated_user = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        assert get_membership(client.tenant_id, unrelated_user.id) is None
        with pytest.raises(AppointmentReferenceNotFoundError):
            create_calendar(
                owner.id,
                client.tenant_id,
                name="Bad Owner",
                owner_user_id=unrelated_user.id,
                timezone="UTC",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated_user.id)


def test_cross_client_calendar_read_denied() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B Only", owner_user_id=owner_b.id, timezone="UTC"
        )
        with pytest.raises(AppointmentAccessDeniedError):
            get_calendar(owner_a.id, client_b.tenant_id, calendar_b.id)
        with pytest.raises(AppointmentAccessDeniedError):
            list_calendars(owner_a.id, client_b.tenant_id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_agency_calendar_mutation_denied() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B Only", owner_user_id=owner_b.id, timezone="UTC"
        )
        with pytest.raises(AppointmentAccessDeniedError):
            update_calendar(owner_a.id, client_b.tenant_id, calendar_b.id, name="Hijacked")
        with pytest.raises(AppointmentAccessDeniedError):
            delete_calendar(owner_a.id, client_b.tenant_id, calendar_b.id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_owner_reaches_own_clients_calendars_via_inherited_subtree() -> None:
    """The agency owner has no direct membership at the client -- only
    inherited SUBTREE reach from provision_agency()."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Reach Test", owner_user_id=owner.id, timezone="UTC"
        )
        fetched = get_calendar(owner.id, client.tenant_id, calendar.id)
        assert fetched.id == calendar.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_calendar() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AppointmentAccessDeniedError):
            create_calendar(
                stranger.id,
                client.tenant_id,
                name="Should Fail",
                owner_user_id=owner.id,
                timezone="UTC",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_explicit_deny_overrides_inherited_subtree_reach_for_appointments() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Visible", owner_user_id=owner.id, timezone="UTC"
        )
        assert calendar.id is not None

        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=CALENDAR_RESOURCE,
            action="create",
            scope_mode=RoleScope.SELF,
        )

        with pytest.raises(AppointmentAccessDeniedError):
            create_calendar(
                owner.id,
                client.tenant_id,
                name="Should Fail",
                owner_user_id=owner.id,
                timezone="UTC",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_or_create_booking_link_is_idempotent_and_scoped_to_the_right_calendar() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar_a = create_calendar(
            owner.id, client.tenant_id, name="A", owner_user_id=owner.id, timezone="UTC"
        )
        calendar_b = create_calendar(
            owner.id, client.tenant_id, name="B", owner_user_id=owner.id, timezone="UTC"
        )
        token_a1 = get_or_create_booking_link(owner.id, client.tenant_id, calendar_a.id)
        token_a2 = get_or_create_booking_link(owner.id, client.tenant_id, calendar_a.id)
        token_b = get_or_create_booking_link(owner.id, client.tenant_id, calendar_b.id)
        assert token_a1 == token_a2
        assert token_a1 != token_b
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
