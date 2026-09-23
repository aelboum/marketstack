"""Generic calendar-event CRUD (Calendar Foundation, docs/ROADMAP.md
Phase 7.5).

Deliberately reuses `CALENDAR_RESOURCE` for authorization, gated by the
parent calendar exactly the way `AvailabilityRule` already is
(`product/appointments/permissions.py`'s own module docstring: "no
separate resource per sub-entity") -- there is no new
`appointments.calendar_event` permission to provision, and no change to
`product/appointments/event_handlers.py`'s existing owner/member grants
is needed as a result.

Every function follows the exact shape `product/appointments/calendars.py`
establishes: authorize via `require()` first, then the real
`tenant_session_scope()` read/write, then `core.audit_log.record()` for
mutations.

**Deliberately does not publish any event and does not touch
`Appointment` at all.** A `CalendarEvent` is a read/write scheduling
projection, never a trigger source -- `Appointment`'s own lifecycle
(`product/appointments/booking.py`) remains the sole origin of
`appointments.appointment.*` automation events and the
`reputation`-integration `.completed` trigger. Creating, editing, or
deleting a `CalendarEvent` -- appointment-backed or not -- never invokes
`product/appointments/booking.py`'s reschedule/cancel/complete/no-show
functions and never dispatches an automation/reputation event. An
appointment-backed `CalendarEvent` is a *view onto* an appointment's
schedule, not a second way to mutate it: `starts_at`/`ends_at`/`title`/
`description` on an appointment-backed row may drift from the
appointment's own truth if edited independently here, exactly as any
other read/write projection can -- this phase does not add the
synchronization layer that would prevent that, because nothing in this
phase requires it (a genuine future concern, not silently resolved).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.appointments.errors import (
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.models import (
    MAX_CALENDAR_EVENT_DESCRIPTION_LENGTH,
    MAX_CALENDAR_EVENT_TITLE_LENGTH,
    Appointment,
    Calendar,
    CalendarEvent,
)
from product.appointments.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.appointments.permissions import CALENDAR_RESOURCE, require


def _validate_time_range(starts_at: datetime, ends_at: datetime) -> None:
    """Identical to `product/appointments/booking.py::_validate_time_range()`
    -- deliberately duplicated, not imported, mirroring
    `product/appointments/pagination.py`'s own documented "duplicate a
    tiny, genuinely shared utility rather than introduce a cross-file
    dependency for it" judgment call."""
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise AppointmentValidationError("starts_at/ends_at must be timezone-aware.")
    if ends_at <= starts_at:
        raise AppointmentValidationError("ends_at must be after starts_at.")


def _validate_title(title: str | None, *, appointment_id: uuid.UUID | None) -> None:
    if title is not None and len(title) > MAX_CALENDAR_EVENT_TITLE_LENGTH:
        raise AppointmentValidationError(
            f"title exceeds {MAX_CALENDAR_EVENT_TITLE_LENGTH} characters."
        )
    if appointment_id is None and (title is None or not title.strip()):
        raise AppointmentValidationError(
            "title is required for a generic calendar event (appointment_id is not set)."
        )


def _validate_description(description: str | None) -> None:
    if description is not None and len(description) > MAX_CALENDAR_EVENT_DESCRIPTION_LENGTH:
        raise AppointmentValidationError(
            f"description exceeds {MAX_CALENDAR_EVENT_DESCRIPTION_LENGTH} characters."
        )


@dataclass(frozen=True, slots=True)
class CalendarEventView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    calendar_id: uuid.UUID
    appointment_id: uuid.UUID | None
    title: str | None
    description: str | None
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    updated_at: datetime


def _to_view(row: CalendarEvent) -> CalendarEventView:
    return CalendarEventView(
        id=row.id,
        tenant_id=row.tenant_id,
        calendar_id=row.calendar_id,
        appointment_id=row.appointment_id,
        title=row.title,
        description=row.description,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_calendar_event(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    calendar_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    title: str | None = None,
    description: str | None = None,
    appointment_id: uuid.UUID | None = None,
) -> CalendarEventView:
    """Raises `AppointmentReferenceNotFoundError` if `calendar_id` (or a
    given `appointment_id`) does not resolve to a real, in-tenant row, and
    `AppointmentValidationError` if the given `appointment_id` belongs to
    a different calendar than `calendar_id` -- an appointment-backed
    event must project the same calendar its appointment is actually
    booked on."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="create")
    _validate_time_range(starts_at, ends_at)
    _validate_title(title, appointment_id=appointment_id)
    _validate_description(description)
    with tenant_session_scope(tenant_id) as session:
        calendar = session.get(Calendar, calendar_id)
        if calendar is None or calendar.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)
        if appointment_id is not None:
            appointment = session.get(Appointment, appointment_id)
            if appointment is None or appointment.tenant_id != tenant_id:
                raise AppointmentReferenceNotFoundError("appointment", appointment_id)
            if appointment.calendar_id != calendar_id:
                raise AppointmentValidationError(
                    "appointment_id does not belong to the given calendar_id."
                )
        row = CalendarEvent(
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            appointment_id=appointment_id,
            title=title,
            description=description,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar_event.create",
        resource_type="appointments.calendar_event",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"calendar_id": str(calendar_id)},
    )
    return _to_view(row)


def get_calendar_event(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_event_id: uuid.UUID
) -> CalendarEventView:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CalendarEvent, calendar_event_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar_event", calendar_event_id)
        session.expunge(row)
    return _to_view(row)


def list_calendar_events(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    calendar_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CalendarEventView]:
    """Every row whose `[starts_at, ends_at)` overlaps `[date_from,
    date_to)` on `calendar_id` -- generic and appointment-backed rows
    alike, in the same result set (the whole point of the Calendar
    Foundation: one query surfaces both kinds on a calendar)."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    if date_from.tzinfo is None or date_to.tzinfo is None:
        raise AppointmentValidationError("date_from/date_to must be timezone-aware.")
    if date_to <= date_from:
        raise AppointmentValidationError("date_to must be after date_from.")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        calendar = session.get(Calendar, calendar_id)
        if calendar is None or calendar.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)
        rows = (
            session.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.tenant_id == tenant_id,
                    CalendarEvent.calendar_id == calendar_id,
                    CalendarEvent.starts_at < date_to,
                    CalendarEvent.ends_at > date_from,
                )
                .order_by(CalendarEvent.starts_at.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_calendar_event(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    calendar_event_id: uuid.UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> CalendarEventView:
    """`calendar_id` and `appointment_id` are deliberately not
    reassignable here -- moving an appointment-backed event to a
    different appointment (or detaching it) is not a "rename", it is a
    different domain operation this phase does not need and does not
    define; delete and recreate if that is genuinely required."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CalendarEvent, calendar_event_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar_event", calendar_event_id)
        new_starts_at = starts_at if starts_at is not None else row.starts_at
        new_ends_at = ends_at if ends_at is not None else row.ends_at
        _validate_time_range(new_starts_at, new_ends_at)
        new_title = title if title is not None else row.title
        _validate_title(new_title, appointment_id=row.appointment_id)
        if description is not None:
            _validate_description(description)
        row.starts_at = new_starts_at
        row.ends_at = new_ends_at
        if title is not None:
            row.title = title
        if description is not None:
            row.description = description
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar_event.update",
        resource_type="appointments.calendar_event",
        resource_id=str(calendar_event_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_calendar_event(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_event_id: uuid.UUID
) -> None:
    """Deletes only the `CalendarEvent` projection row -- never touches
    the `Appointment` it may be backed by (see module docstring)."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CalendarEvent, calendar_event_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar_event", calendar_event_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar_event.delete",
        resource_type="appointments.calendar_event",
        resource_id=str(calendar_event_id),
        outcome=AuditOutcome.SUCCESS,
    )


__all__ = [
    "CalendarEventView",
    "create_calendar_event",
    "delete_calendar_event",
    "get_calendar_event",
    "list_calendar_events",
    "update_calendar_event",
]
