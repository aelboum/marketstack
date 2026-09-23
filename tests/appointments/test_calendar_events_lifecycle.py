"""`CalendarEvent` CRUD, isolation, and generic-vs-appointment-backed
validation (Calendar Foundation, docs/ROADMAP.md Phase 7.5). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from infra.db import IntegrityError, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.appointments.booking import book_appointment
from product.appointments.calendar_events import (
    create_calendar_event,
    delete_calendar_event,
    get_calendar_event,
    list_calendar_events,
    update_calendar_event,
)
from product.appointments.calendars import create_calendar
from product.appointments.errors import (
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.models import Appointment, CalendarEvent

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _slot(day: int, hour: int = 9) -> tuple[datetime, datetime]:
    start = datetime(2026, 8, day, hour, 0, tzinfo=UTC)
    return start, start + timedelta(hours=1)


def _booked_appointment(owner_id, tenant_id, calendar_id, day: int, hour: int = 9):
    starts_at, ends_at = _slot(day, hour)
    return book_appointment(
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        contact_email=f"{_name('lead')}@example.com",
        contact_first_name="Cal",
        contact_last_name="Event",
        starts_at=starts_at,
        ends_at=ends_at,
        actor_user_id=owner_id,
    )


def test_generic_event_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(1)
        event = create_calendar_event(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            starts_at=starts_at,
            ends_at=ends_at,
            title="Team meeting",
            description="Weekly sync",
        )
        assert event.appointment_id is None
        assert event.title == "Team meeting"

        fetched = get_calendar_event(owner.id, client.tenant_id, event.id)
        assert fetched.id == event.id

        listed = list_calendar_events(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            date_from=datetime(2026, 8, 1, tzinfo=UTC),
            date_to=datetime(2026, 8, 2, tzinfo=UTC),
        )
        assert any(e.id == event.id for e in listed)

        new_starts_at, new_ends_at = _slot(1, hour=14)
        updated = update_calendar_event(
            owner.id,
            client.tenant_id,
            event.id,
            title="Internal meeting",
            starts_at=new_starts_at,
            ends_at=new_ends_at,
        )
        assert updated.title == "Internal meeting"
        assert updated.starts_at == new_starts_at

        delete_calendar_event(owner.id, client.tenant_id, event.id)
        with pytest.raises(AppointmentReferenceNotFoundError):
            get_calendar_event(owner.id, client.tenant_id, event.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_appointment_backed_event_created_without_title() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        appt = _booked_appointment(owner.id, client.tenant_id, calendar.id, day=2)
        event = create_calendar_event(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            starts_at=appt.starts_at,
            ends_at=appt.ends_at,
            appointment_id=appt.id,
        )
        assert event.title is None
        assert event.appointment_id == appt.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_generic_event_without_title_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(3)
        with pytest.raises(AppointmentValidationError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=calendar.id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_time_range_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(4)
        with pytest.raises(AppointmentValidationError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=calendar.id,
                starts_at=ends_at,
                ends_at=starts_at,
                title="Backwards",
            )
        with pytest.raises(AppointmentValidationError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=calendar.id,
                starts_at=starts_at.replace(tzinfo=None),
                ends_at=ends_at,
                title="Naive",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_calendar_and_appointment_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(5)
        with pytest.raises(AppointmentReferenceNotFoundError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=uuid.uuid4(),
                starts_at=starts_at,
                ends_at=ends_at,
                title="Ghost calendar",
            )
        with pytest.raises(AppointmentReferenceNotFoundError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=calendar.id,
                starts_at=starts_at,
                ends_at=ends_at,
                appointment_id=uuid.uuid4(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_appointment_backed_event_must_match_calendar() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar_a = create_calendar(
            owner.id, client.tenant_id, name="A", owner_user_id=owner.id, timezone="UTC"
        )
        calendar_b = create_calendar(
            owner.id, client.tenant_id, name="B", owner_user_id=owner.id, timezone="UTC"
        )
        appt = _booked_appointment(owner.id, client.tenant_id, calendar_a.id, day=6)
        with pytest.raises(AppointmentValidationError):
            create_calendar_event(
                owner.id,
                client.tenant_id,
                calendar_id=calendar_b.id,
                starts_at=appt.starts_at,
                ends_at=appt.ends_at,
                appointment_id=appt.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_calendar_event_read_is_non_enumerating() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_a = create_calendar(
            owner_a.id, client_a.tenant_id, name="A", owner_user_id=owner_a.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        event = create_calendar_event(
            owner_a.id,
            client_a.tenant_id,
            calendar_id=calendar_a.id,
            starts_at=starts_at,
            ends_at=ends_at,
            title="Tenant A only",
        )
        with pytest.raises(AppointmentReferenceNotFoundError):
            get_calendar_event(owner_b.id, client_b.tenant_id, event.id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_tenant_calendar_reference_rejected_by_database_constraint_directly() -> None:
    """The composite FK on calendar_events.calendar_id -- proven by
    bypassing the service layer entirely, mirrors
    tests/appointments/test_booking_integration.py's identical proof for
    appointments.appointments.calendar_id."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B Only", owner_user_id=owner_b.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = CalendarEvent(
                    tenant_id=client_a.tenant_id,
                    calendar_id=calendar_b.id,
                    title="Should never insert",
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_deleting_appointment_unlinks_calendar_event_but_keeps_it() -> None:
    """`ON DELETE SET NULL (appointment_id)`, column-scoped -- mirrors
    `test_booking_integration.py::test_deleting_contact_unlinks_appointment
    _but_keeps_booking_history()`'s identical proof for `contact_id`.
    Simulates the one real caller of this path (`product/appointments
    /purge.py`) by deleting the `Appointment` row directly -- purge itself
    deletes `CalendarEvent` rows first, so this exercises the FK behavior
    in isolation rather than purge's own ordering."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        appt = _booked_appointment(owner.id, client.tenant_id, calendar.id, day=9)
        event = create_calendar_event(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            starts_at=appt.starts_at,
            ends_at=appt.ends_at,
            title="Kept title",
            appointment_id=appt.id,
        )
        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, appt.id)
            session.delete(row)

        refetched = get_calendar_event(owner.id, client.tenant_id, event.id)
        assert refetched.appointment_id is None
        assert refetched.title == "Kept title"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
