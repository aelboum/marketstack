"""`list_appointments()` -- the staff-facing read endpoint added by
docs/ROADMAP.md Phase 28 (Command Center & Navigation Redesign): before
this, no authenticated way existed to list appointments at all (see
`product/appointments/booking.py::list_appointments()`'s own docstring).
Real disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.appointments.booking import book_appointment, list_appointments
from product.appointments.calendars import create_calendar
from product.appointments.errors import AppointmentAccessDeniedError

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _slot(day: int, hour: int) -> tuple[datetime, datetime]:
    start = datetime(2026, 6, day, hour, 0, tzinfo=UTC)
    return start, start + timedelta(hours=1)


def _book(owner_id, tenant_id, calendar_id, day: int, hour: int):
    starts_at, ends_at = _slot(day, hour)
    return book_appointment(
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        contact_email=f"lead-{uuid.uuid4().hex[:8]}@example.com",
        contact_first_name="Lead",
        contact_last_name="Person",
        starts_at=starts_at,
        ends_at=ends_at,
        actor_user_id=owner_id,
    )


def test_list_appointments_orders_chronologically_and_filters_by_date_range() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        later = _book(owner.id, client.tenant_id, calendar.id, day=10, hour=14)
        earlier = _book(owner.id, client.tenant_id, calendar.id, day=10, hour=9)
        outside_range = _book(owner.id, client.tenant_id, calendar.id, day=20, hour=9)

        results = list_appointments(
            owner.id,
            client.tenant_id,
            starts_after=datetime(2026, 6, 10, 0, 0, tzinfo=UTC),
            starts_before=datetime(2026, 6, 11, 0, 0, tzinfo=UTC),
        )

        assert [row.id for row in results] == [earlier.id, later.id]
        assert outside_range.id not in [row.id for row in results]
    finally:
        cleanup_tenant_tree(client.tenant_id)
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)


def test_list_appointments_is_tenant_isolated() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        calendar_a = create_calendar(
            owner.id, client_a.tenant_id, name="A", owner_user_id=owner.id, timezone="UTC"
        )
        calendar_b = create_calendar(
            owner.id, client_b.tenant_id, name="B", owner_user_id=owner.id, timezone="UTC"
        )
        appt_a = _book(owner.id, client_a.tenant_id, calendar_a.id, day=10, hour=9)
        _book(owner.id, client_b.tenant_id, calendar_b.id, day=10, hour=9)

        results = list_appointments(owner.id, client_a.tenant_id)

        assert [row.id for row in results] == [appt_a.id]
    finally:
        cleanup_tenant_tree(client_a.tenant_id)
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner.id)


def test_list_appointments_denies_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AppointmentAccessDeniedError):
            list_appointments(stranger.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id)
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_list_appointments_route_returns_appointments_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        booked = _book(owner.id, client.tenant_id, calendar.id, day=10, hour=9)

        app = create_app()
        http_client = TestClient(app)
        response = http_client.get(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments",
            headers=_auth_headers(owner.id),
            params={
                "starts_after": "2026-06-10T00:00:00Z",
                "starts_before": "2026-06-11T00:00:00Z",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert [row["id"] for row in body] == [str(booked.id)]
    finally:
        cleanup_tenant_tree(client.tenant_id)
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id)
