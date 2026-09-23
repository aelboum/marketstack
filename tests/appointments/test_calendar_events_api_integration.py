"""The `CalendarEvent` HTTP API (Calendar Foundation API phase,
docs/ROADMAP.md Phase 7.5's own "No HTTP routes added this pass"
deferral, closed here): list/create/update/delete over
`product/appointments/routes.py`'s `/calendar-events` routes. Real
disposable Postgres. Marked `integration`, excluded from the default
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
from product.appointments.booking import book_appointment
from product.appointments.calendar_events import (
    create_calendar_event,
    list_calendar_events,
)
from product.appointments.calendars import create_calendar
from product.appointments.models import STATUS_CONFIRMED, Appointment
from infra.db import tenant_session_scope

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


def _slot(day: int, hour: int = 9) -> tuple[datetime, datetime]:
    start = datetime(2026, 10, day, hour, 0, tzinfo=UTC)
    return start, start + timedelta(hours=1)


def _api() -> TestClient:
    return TestClient(create_app())


# --- List ---------------------------------------------------------------------


def test_list_returns_empty_when_nothing_scheduled() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        response = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            params={"starts_after": "2026-10-01T00:00:00Z", "starts_before": "2026-10-02T00:00:00Z"},
        )
        assert response.status_code == 200
        assert response.json() == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_returns_events_in_window_deterministically_ordered() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_1, ends_1 = _slot(5, 14)
        starts_2, ends_2 = _slot(5, 9)
        event_late = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_1, ends_at=ends_1, title="Later"
        )
        event_early = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_2, ends_at=ends_2, title="Earlier"
        )

        response = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            params={"starts_after": "2026-10-05T00:00:00Z", "starts_before": "2026-10-06T00:00:00Z"},
        )

        assert response.status_code == 200
        body = response.json()
        assert [row["id"] for row in body] == [str(event_early.id), str(event_late.id)]
        assert body[0]["title"] == "Earlier"
        assert body[0]["calendar_id"] == str(calendar.id)
        assert body[0]["appointment_id"] is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_excludes_events_outside_the_requested_window() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        inside_start, inside_end = _slot(5)
        outside_start, outside_end = _slot(20)
        create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=inside_start, ends_at=inside_end, title="In"
        )
        create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=outside_start, ends_at=outside_end, title="Out"
        )

        response = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            params={"starts_after": "2026-10-01T00:00:00Z", "starts_before": "2026-10-10T00:00:00Z"},
        )

        body = response.json()
        assert [row["title"] for row in body] == ["In"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_filters_by_calendar_id_and_defaults_to_every_calendar() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar_a = create_calendar(
            owner.id, client.tenant_id, name="A", owner_user_id=owner.id, timezone="UTC"
        )
        calendar_b = create_calendar(
            owner.id, client.tenant_id, name="B", owner_user_id=owner.id, timezone="UTC"
        )
        starts_a, ends_a = _slot(5)
        starts_b, ends_b = _slot(6)
        create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar_a.id, starts_at=starts_a, ends_at=ends_a, title="A event"
        )
        create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar_b.id, starts_at=starts_b, ends_at=ends_b, title="B event"
        )
        params = {"starts_after": "2026-10-01T00:00:00Z", "starts_before": "2026-10-10T00:00:00Z"}
        headers = _auth_headers(owner.id)

        filtered = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=headers,
            params={**params, "calendar_id": str(calendar_a.id)},
        )
        assert [row["title"] for row in filtered.json()] == ["A event"]

        unfiltered = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events", headers=headers, params=params
        )
        assert {row["title"] for row in unfiltered.json()} == {"A event", "B event"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_is_tenant_isolated() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_a = create_calendar(
            owner_a.id, client_a.tenant_id, name="A", owner_user_id=owner_a.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(5)
        create_calendar_event(
            owner_a.id, client_a.tenant_id, calendar_id=calendar_a.id, starts_at=starts_at, ends_at=ends_at, title="A only"
        )

        response = _api().get(
            f"/v1/appointments/tenants/{client_b.tenant_id}/calendar-events",
            headers=_auth_headers(owner_b.id),
            params={"starts_after": "2026-10-01T00:00:00Z", "starts_before": "2026-10-10T00:00:00Z"},
        )
        assert response.status_code == 200
        assert response.json() == []
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_list_requires_authentication() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        response = _api().get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            params={"starts_after": "2026-10-01T00:00:00Z", "starts_before": "2026-10-02T00:00:00Z"},
        )
        assert response.status_code == 401
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Create ---------------------------------------------------------------------


def test_create_generic_event_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            json={
                "calendar_id": str(calendar.id),
                "title": "Team meeting",
                "description": "Weekly sync",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Team meeting"
        assert body["description"] == "Weekly sync"
        assert body["calendar_id"] == str(calendar.id)
        assert body["appointment_id"] is None
        assert body["tenant_id"] == str(client.tenant_id)
        assert "id" in body and "created_at" in body and "updated_at" in body
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_without_title_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            json={
                "calendar_id": str(calendar.id),
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert response.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_with_invalid_date_range_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            json={
                "calendar_id": str(calendar.id),
                "title": "Backwards",
                "starts_at": ends_at.isoformat(),
                "ends_at": starts_at.isoformat(),
            },
        )
        assert response.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_with_naive_datetime_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            json={
                "calendar_id": str(calendar.id),
                "title": "Naive",
                "starts_at": "2026-10-07T09:00:00",
                "ends_at": "2026-10-07T10:00:00",
            },
        )
        assert response.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_with_unknown_calendar_is_non_enumerating_404() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            headers=_auth_headers(owner.id),
            json={
                "calendar_id": str(uuid.uuid4()),
                "title": "Ghost",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_rejects_cross_tenant_calendar() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B only", owner_user_id=owner_b.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client_a.tenant_id}/calendar-events",
            headers=_auth_headers(owner_a.id),
            json={
                "calendar_id": str(calendar_b.id),
                "title": "Should not create",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_create_requires_authentication() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7)
        response = _api().post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events",
            json={
                "calendar_id": str(calendar.id),
                "title": "No auth",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert response.status_code == 401
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Update ---------------------------------------------------------------------


def test_update_title_and_description_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Old"
        )

        response = _api().patch(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner.id),
            json={"title": "New", "description": "Updated"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "New"
        assert body["description"] == "Updated"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_time_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Old"
        )
        new_starts_at, new_ends_at = _slot(8, 14)

        response = _api().patch(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner.id),
            json={"starts_at": new_starts_at.isoformat(), "ends_at": new_ends_at.isoformat()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["starts_at"] == new_starts_at.isoformat()
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_with_invalid_date_range_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Old"
        )

        response = _api().patch(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner.id),
            json={"starts_at": ends_at.isoformat(), "ends_at": starts_at.isoformat()},
        )
        assert response.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_is_cross_tenant_protected() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_a = create_calendar(
            owner_a.id, client_a.tenant_id, name="A", owner_user_id=owner_a.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        event = create_calendar_event(
            owner_a.id, client_a.tenant_id, calendar_id=calendar_a.id, starts_at=starts_at, ends_at=ends_at, title="A only"
        )

        response = _api().patch(
            f"/v1/appointments/tenants/{client_b.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner_b.id),
            json={"title": "Hijacked"},
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_update_unknown_event_is_non_enumerating_404() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        response = _api().patch(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{uuid.uuid4()}",
            headers=_auth_headers(owner.id),
            json={"title": "Nope"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_requires_authentication() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Old"
        )
        response = _api().patch(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            json={"title": "No auth"},
        )
        assert response.status_code == 401
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Delete ---------------------------------------------------------------------


def test_delete_generic_event_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(9)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Gone soon"
        )

        response = _api().delete(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 204

        remaining = list_calendar_events(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            date_from=datetime(2026, 10, 1, tzinfo=UTC),
            date_to=datetime(2026, 10, 15, tzinfo=UTC),
        )
        assert remaining == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_delete_unknown_event_is_non_enumerating_404() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        response = _api().delete(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{uuid.uuid4()}",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found."}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_delete_requires_authentication() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(9)
        event = create_calendar_event(
            owner.id, client.tenant_id, calendar_id=calendar.id, starts_at=starts_at, ends_at=ends_at, title="Untouched"
        )
        response = _api().delete(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}"
        )
        assert response.status_code == 401
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_delete_is_tenant_isolated() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_a = create_calendar(
            owner_a.id, client_a.tenant_id, name="A", owner_user_id=owner_a.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(9)
        event = create_calendar_event(
            owner_a.id, client_a.tenant_id, calendar_id=calendar_a.id, starts_at=starts_at, ends_at=ends_at, title="A only"
        )

        response = _api().delete(
            f"/v1/appointments/tenants/{client_b.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner_b.id),
        )
        assert response.status_code == 404

        still_there = list_calendar_events(
            owner_a.id,
            client_a.tenant_id,
            calendar_id=calendar_a.id,
            date_from=datetime(2026, 10, 1, tzinfo=UTC),
            date_to=datetime(2026, 10, 15, tzinfo=UTC),
        )
        assert [e.id for e in still_there] == [event.id]
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_deleting_an_appointment_backed_event_never_touches_the_appointment() -> None:
    """The core Calendar-Foundation guarantee, exercised over real HTTP:
    a `CalendarEvent` is a projection, never a second way to mutate an
    `Appointment` -- see `delete_calendar_event()`'s own docstring."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(10)
        appt = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email=f"{_name('lead')}@example.com",
            contact_first_name="Cal",
            contact_last_name="Event",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        event = create_calendar_event(
            owner.id,
            client.tenant_id,
            calendar_id=calendar.id,
            starts_at=starts_at,
            ends_at=ends_at,
            appointment_id=appt.id,
        )

        response = _api().delete(
            f"/v1/appointments/tenants/{client.tenant_id}/calendar-events/{event.id}",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 204

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, appt.id)
            assert row is not None
            assert row.status == STATUS_CONFIRMED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
