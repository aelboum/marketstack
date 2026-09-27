"""`staff_complete_appointment()`/`staff_no_show_appointment()` and the
five Appointments lifecycle events (docs/ROADMAP.md Phase 23, "Customer
Lifecycle Loop"). Real disposable Postgres. Marked `integration`,
excluded from the default `pytest` run.

Imports `product.appointments.event_handlers` solely for its module-level
`subscribe("agency.role_provisioned", ...)` side effect -- mirrors
`tests/reputation/_cleanup.py`'s own identical, already-documented
precedent: this file's own tests exercise `appointments.calendar`/
`appointments.appointment` permissions directly (via `create_calendar()`/
`staff_complete_appointment()` etc.), with no guarantee some *other*,
unrelated test file in the same `pytest` invocation happens to trigger
that registration first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.appointments import event_handlers as _appointments_event_handlers  # noqa: F401
from product.appointments.booking import (
    APPOINTMENT_CANCELLED_EVENT_TYPE,
    APPOINTMENT_COMPLETED_EVENT_TYPE,
    APPOINTMENT_NO_SHOW_EVENT_TYPE,
    APPOINTMENT_RESCHEDULED_EVENT_TYPE,
    book_appointment,
    staff_cancel_appointment,
    staff_complete_appointment,
    staff_no_show_appointment,
    staff_reschedule_appointment,
)
from product.appointments.calendars import create_calendar
from product.appointments.errors import (
    AppointmentAccessDeniedError,
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.models import STATUS_COMPLETED, STATUS_NO_SHOW
from product.foundation.events import subscribe

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _slot(day: int, hour: int) -> tuple[datetime, datetime]:
    start = datetime(2026, 7, day, hour, 0, tzinfo=UTC)
    return start, start + timedelta(hours=1)


def _booked(owner_id, tenant_id, day: int, hour: int = 9):
    calendar = create_calendar(
        owner_id, tenant_id, name="Cal", owner_user_id=owner_id, timezone="UTC"
    )
    starts_at, ends_at = _slot(day, hour)
    return calendar, book_appointment(
        tenant_id=tenant_id,
        calendar_id=calendar.id,
        contact_email=f"{_name('lead')}@example.com",
        contact_first_name="Life",
        contact_last_name="Cycle",
        starts_at=starts_at,
        ends_at=ends_at,
        actor_user_id=owner_id,
    )


# --- Complete / no-show: valid transitions -----------------------------------


def test_complete_appointment_transitions_and_publishes_event_with_actor() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []
    subscribe(APPOINTMENT_COMPLETED_EVENT_TYPE, received.append)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 1)
        completed = staff_complete_appointment(owner.id, client.tenant_id, appt.id)
        assert completed.status == STATUS_COMPLETED

        matching = [e for e in received if e.payload.get("appointment_id") == str(appt.id)]
        assert len(matching) == 1
        assert matching[0].payload == {
            "appointment_id": str(appt.id),
            "calendar_id": str(appt.calendar_id),
            "contact_id": str(appt.contact_id),
            "actor_user_id": str(owner.id),
        }
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_no_show_appointment_transitions_and_publishes_bounded_event() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []
    subscribe(APPOINTMENT_NO_SHOW_EVENT_TYPE, received.append)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 2)
        no_show = staff_no_show_appointment(owner.id, client.tenant_id, appt.id)
        assert no_show.status == STATUS_NO_SHOW

        matching = [e for e in received if e.payload.get("appointment_id") == str(appt.id)]
        assert len(matching) == 1
        # No actor_user_id here -- only .completed carries one (module
        # docstring's own deliberate, narrow exception).
        assert matching[0].payload == {
            "appointment_id": str(appt.id),
            "calendar_id": str(appt.calendar_id),
            "contact_id": str(appt.contact_id),
        }
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid transitions -------------------------------------------------------


def test_completing_a_non_confirmed_appointment_fails_explicitly() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 3)
        staff_cancel_appointment(owner.id, client.tenant_id, appt.id)
        with pytest.raises(AppointmentValidationError):
            staff_complete_appointment(owner.id, client.tenant_id, appt.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_marking_no_show_twice_fails_explicitly() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 4)
        staff_no_show_appointment(owner.id, client.tenant_id, appt.id)
        with pytest.raises(AppointmentValidationError):
            staff_no_show_appointment(owner.id, client.tenant_id, appt.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancelling_a_completed_appointment_is_now_rejected() -> None:
    """docs/ROADMAP.md Phase 23 tightened `staff_cancel_appointment()`'s
    own guard -- previously only "not already cancelled," now "must
    still be confirmed" -- to close the newly-reachable
    completed/no_show -> cancel path."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 5)
        staff_complete_appointment(owner.id, client.tenant_id, appt.id)
        with pytest.raises(AppointmentValidationError):
            staff_cancel_appointment(owner.id, client.tenant_id, appt.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_rescheduling_a_no_show_appointment_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 6)
        staff_no_show_appointment(owner.id, client.tenant_id, appt.id)
        new_start, new_end = _slot(6, 15)
        with pytest.raises(AppointmentValidationError):
            staff_reschedule_appointment(
                owner.id, client.tenant_id, appt.id, new_starts_at=new_start, new_ends_at=new_end
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_completing_an_unknown_appointment_is_non_enumerating() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AppointmentReferenceNotFoundError):
            staff_complete_appointment(owner.id, client.tenant_id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Cancel/reschedule now publish events too ---------------------------------


def test_staff_cancel_and_reschedule_now_publish_events() -> None:
    """Previously zero events -- docs/ROADMAP.md Phase 23's own scope
    item (a)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    cancelled_events = []
    rescheduled_events = []
    subscribe(APPOINTMENT_CANCELLED_EVENT_TYPE, cancelled_events.append)
    subscribe(APPOINTMENT_RESCHEDULED_EVENT_TYPE, rescheduled_events.append)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 7)
        new_start, new_end = _slot(7, 15)
        staff_reschedule_appointment(
            owner.id, client.tenant_id, appt.id, new_starts_at=new_start, new_ends_at=new_end
        )
        staff_cancel_appointment(owner.id, client.tenant_id, appt.id)

        assert any(e.payload.get("appointment_id") == str(appt.id) for e in rescheduled_events)
        assert any(e.payload.get("appointment_id") == str(appt.id) for e in cancelled_events)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Authorization / tenant isolation ------------------------------------------


def test_unrelated_actor_cannot_complete_or_no_show() -> None:
    owner = make_user()
    attacker = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _calendar, appt = _booked(owner.id, client.tenant_id, 8)
        with pytest.raises(AppointmentAccessDeniedError):
            staff_complete_appointment(attacker.id, client.tenant_id, appt.id)
        with pytest.raises(AppointmentAccessDeniedError):
            staff_no_show_appointment(attacker.id, client.tenant_id, appt.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, attacker.id)


def test_complete_is_tenant_isolated() -> None:
    """Tenant A's owner cannot complete tenant B's appointment even by
    guessing its id -- proven against a real, existing appointment id."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _calendar_b, appt_b = _booked(owner_b.id, client_b.tenant_id, 9)
        with pytest.raises(AppointmentReferenceNotFoundError):
            staff_complete_appointment(owner_a.id, client_a.tenant_id, appt_b.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- HTTP layer -----------------------------------------------------------------


def test_complete_and_no_show_routes_over_http() -> None:
    from core.identity.sessions import issue_session
    from fastapi.testclient import TestClient
    from product.api.main import create_app

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _session, raw_token = issue_session(owner.id)
        headers = {"Authorization": f"Bearer {raw_token}"}
        api = TestClient(create_app())

        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(10, 9)
        create_resp = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments",
            json={
                "calendar_id": str(calendar.id),
                "contact_email": "http-lifecycle@example.com",
                "contact_first_name": "Http",
                "contact_last_name": "Lifecycle",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        appointment_id = create_resp.json()["id"]

        complete_resp = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments/{appointment_id}/complete",
            headers=headers,
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["status"] == STATUS_COMPLETED

        no_show_resp = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments/{appointment_id}/no-show",
            headers=headers,
        )
        assert no_show_resp.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_complete_route_requires_authentication() -> None:
    from fastapi.testclient import TestClient
    from product.api.main import create_app

    api = TestClient(create_app())
    resp = api.post(
        f"/v1/appointments/tenants/{uuid.uuid4()}/appointments/{uuid.uuid4()}/complete"
    )
    assert resp.status_code == 401
