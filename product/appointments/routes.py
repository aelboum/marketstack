"""The Appointments API (docs/ROADMAP.md Phase 7), mounted under
`/v1/appointments` in `product/api/main.py`.

**Ingress dependency choice** -- identical reasoning to
`product/marketing/routes.py`'s own module docstring
(`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum): every authenticated route below uses
`api.dependencies.get_current_actor`, never `get_tenant_context()`/
`require_permission()`. Every `product/appointments/*.py` service
function performs its own `core.rbac.can()` check via
`product.appointments.permissions.require()` before touching any
`appointments.*` row.

**Non-enumeration**: `AppointmentAccessDeniedError`,
`AppointmentReferenceNotFoundError` (authenticated paths) and
`AppointmentTokenInvalidError` (public paths) all map to the identical
`404` shape `api.errors.not_found()` uses elsewhere in this platform.
`AppointmentValidationError` maps to `400`.
`AppointmentSlotUnavailableError` -- the service-layer translation of the
real, database-enforced `EXCLUDE` constraint violation -- maps to a
`409`, with a fixed, generic `detail` string carrying no internal detail
(no constraint name, no SQL), mirroring every other error helper's own
"fixed message, never the exception's own text" discipline
(`api/errors.py`'s own module docstring, which ships no ready-made 409
helper for this shape, so this module defines its own inline).

**Public booking/manage routes are rate-limited and non-enumerating** --
mirrors `product/marketing/routes.py::submit_form_route()`/
`_enforce_public_rate_limit()` exactly; see
`product/appointments/booking.py`'s own module docstring for why these
specific routes (real mutations on a real resource) get the stricter
treatment `product/marketing/tracking.py`'s read-only routes deliberately
do not.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from api.dependencies import get_current_actor
from api.errors import not_found, rate_limited, service_unavailable
from fastapi import APIRouter, Depends, HTTPException, status
from infra.ratelimit import (
    RateLimitBackendError,
    RateLimitExceededError,
    enforce_rate_limit,
    get_ratelimit_config,
)
from pydantic import BaseModel, Field

from product.appointments.availability import (
    AvailabilityRuleView,
    AvailableSlot,
    compute_available_slots,
    create_availability_rule,
    delete_availability_rule,
    list_availability_rules,
)
from product.appointments.booking import (
    AppointmentView,
    book_appointment,
    list_appointments,
    public_book_appointment,
    public_cancel_appointment,
    public_reschedule_appointment,
    resolve_manage_token,
    staff_cancel_appointment,
    staff_reschedule_appointment,
)
from product.appointments.calendars import (
    CalendarView,
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
    AppointmentSlotUnavailableError,
    AppointmentTokenInvalidError,
    AppointmentValidationError,
)
from product.appointments.models import MAX_CALENDAR_NAME_LENGTH, MINUTES_PER_DAY
from product.appointments.pagination import DEFAULT_PAGE_SIZE
from product.appointments.reminders import send_due_reminders

router = APIRouter(prefix="/v1/appointments", tags=["appointments"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    AppointmentAccessDeniedError,
    AppointmentReferenceNotFoundError,
)
_PUBLIC_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (AppointmentTokenInvalidError,)
_VALIDATION_ERRORS: tuple[type[Exception], ...] = (AppointmentValidationError,)
_SLOT_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (AppointmentSlotUnavailableError,)


def _slot_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="The requested slot is no longer available.",
    )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _SLOT_UNAVAILABLE_ERRORS:
        raise _slot_unavailable() from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except _PUBLIC_NOT_FOUND_ERRORS:
        raise not_found("resource") from None


async def _enforce_public_rate_limit(key: str) -> None:
    """Mirrors `product/marketing/routes.py::_enforce_public_rate_limit()`
    exactly -- fail-closed, keyed by the caller-chosen public token rather
    than a tenant (there is no tenant context yet)."""
    try:
        await enforce_rate_limit(key, config=get_ratelimit_config())
    except RateLimitExceededError as exc:
        raise rate_limited(exc.retry_after_seconds) from None
    except RateLimitBackendError:
        raise service_unavailable(5) from None


# --- Request bodies ----------------------------------------------------------


class CreateCalendarRequest(BaseModel):
    name: str = Field(max_length=MAX_CALENDAR_NAME_LENGTH)
    owner_user_id: uuid.UUID
    timezone: str


class UpdateCalendarRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_CALENDAR_NAME_LENGTH)
    owner_user_id: uuid.UUID | None = None
    timezone: str | None = None


class CreateAvailabilityRuleRequest(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: int = Field(ge=0, lt=MINUTES_PER_DAY)
    end_time: int = Field(gt=0, le=MINUTES_PER_DAY)


class BookAppointmentRequest(BaseModel):
    calendar_id: uuid.UUID
    contact_email: str = Field(max_length=320)
    contact_first_name: str = Field(max_length=255)
    contact_last_name: str = Field(max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    starts_at: datetime
    ends_at: datetime


class PublicBookAppointmentRequest(BaseModel):
    contact_email: str = Field(max_length=320)
    contact_first_name: str = Field(max_length=255)
    contact_last_name: str = Field(max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    starts_at: datetime
    ends_at: datetime


class RescheduleAppointmentRequest(BaseModel):
    new_starts_at: datetime
    new_ends_at: datetime


# --- Serialization -------------------------------------------------------------


def _calendar_dict(view: CalendarView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "owner_user_id": str(view.owner_user_id),
        "timezone": view.timezone,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _rule_dict(view: AvailabilityRuleView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "calendar_id": str(view.calendar_id),
        "day_of_week": view.day_of_week,
        "start_time": view.start_time,
        "end_time": view.end_time,
        "created_at": view.created_at.isoformat(),
    }


def _slot_dict(slot: AvailableSlot) -> dict[str, object]:
    return {"starts_at": slot.starts_at.isoformat(), "ends_at": slot.ends_at.isoformat()}


def _appointment_dict(view: AppointmentView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "calendar_id": str(view.calendar_id),
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "starts_at": view.starts_at.isoformat(),
        "ends_at": view.ends_at.isoformat(),
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


# --- Calendars (authenticated) --------------------------------------------------


@router.post("/tenants/{tenant_id}/calendars", status_code=status.HTTP_201_CREATED)
def create_calendar_route(
    tenant_id: uuid.UUID,
    body: CreateCalendarRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _calendar_dict(
        _call(
            create_calendar,
            actor_id,
            tenant_id,
            name=body.name,
            owner_user_id=body.owner_user_id,
            timezone=body.timezone,
        )
    )


@router.get("/tenants/{tenant_id}/calendars")
def list_calendars_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _calendar_dict(v)
        for v in _call(list_calendars, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/calendars/{calendar_id}")
def get_calendar_route(
    tenant_id: uuid.UUID, calendar_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _calendar_dict(_call(get_calendar, actor_id, tenant_id, calendar_id))


@router.patch("/tenants/{tenant_id}/calendars/{calendar_id}")
def update_calendar_route(
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    body: UpdateCalendarRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _calendar_dict(
        _call(
            update_calendar,
            actor_id,
            tenant_id,
            calendar_id,
            name=body.name,
            owner_user_id=body.owner_user_id,
            timezone=body.timezone,
        )
    )


@router.delete(
    "/tenants/{tenant_id}/calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_calendar_route(
    tenant_id: uuid.UUID, calendar_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_calendar, actor_id, tenant_id, calendar_id)


@router.post("/tenants/{tenant_id}/calendars/{calendar_id}/booking-link")
def get_or_create_booking_link_route(
    tenant_id: uuid.UUID, calendar_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return {"link_token": _call(get_or_create_booking_link, actor_id, tenant_id, calendar_id)}


# --- Availability rules (authenticated) ------------------------------------------


@router.post(
    "/tenants/{tenant_id}/calendars/{calendar_id}/availability-rules",
    status_code=status.HTTP_201_CREATED,
)
def create_availability_rule_route(
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    body: CreateAvailabilityRuleRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _rule_dict(
        _call(
            create_availability_rule,
            actor_id,
            tenant_id,
            calendar_id,
            day_of_week=body.day_of_week,
            start_time=body.start_time,
            end_time=body.end_time,
        )
    )


@router.get("/tenants/{tenant_id}/calendars/{calendar_id}/availability-rules")
def list_availability_rules_route(
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [_rule_dict(v) for v in _call(list_availability_rules, actor_id, tenant_id, calendar_id)]


@router.delete(
    "/tenants/{tenant_id}/calendars/{calendar_id}/availability-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_availability_rule_route(
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    rule_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_availability_rule, actor_id, tenant_id, calendar_id, rule_id)


@router.get("/tenants/{tenant_id}/calendars/{calendar_id}/available-slots")
def available_slots_route(
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    date_from: date,
    date_to: date,
    slot_duration_minutes: int,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _slot_dict(v)
        for v in _call(
            compute_available_slots,
            actor_id,
            tenant_id,
            calendar_id,
            date_from=date_from,
            date_to=date_to,
            slot_duration_minutes=slot_duration_minutes,
        )
    ]


# --- Appointments (authenticated: staff booking, reschedule, cancel) ------------


@router.post("/tenants/{tenant_id}/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment_route(
    tenant_id: uuid.UUID,
    body: BookAppointmentRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _appointment_dict(
        _call(
            book_appointment,
            tenant_id=tenant_id,
            calendar_id=body.calendar_id,
            contact_email=body.contact_email,
            contact_first_name=body.contact_first_name,
            contact_last_name=body.contact_last_name,
            contact_phone=body.contact_phone,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            actor_user_id=actor_id,
        )
    )


@router.get("/tenants/{tenant_id}/appointments")
def list_appointments_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _appointment_dict(v)
        for v in _call(
            list_appointments,
            actor_id,
            tenant_id,
            starts_after=starts_after,
            starts_before=starts_before,
            limit=limit,
            offset=offset,
        )
    ]


@router.post("/tenants/{tenant_id}/appointments/{appointment_id}/cancel")
def staff_cancel_appointment_route(
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _appointment_dict(_call(staff_cancel_appointment, actor_id, tenant_id, appointment_id))


@router.post("/tenants/{tenant_id}/appointments/{appointment_id}/reschedule")
def staff_reschedule_appointment_route(
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID,
    body: RescheduleAppointmentRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _appointment_dict(
        _call(
            staff_reschedule_appointment,
            actor_id,
            tenant_id,
            appointment_id,
            new_starts_at=body.new_starts_at,
            new_ends_at=body.new_ends_at,
        )
    )


@router.post("/tenants/{tenant_id}/reminders/sweep")
def sweep_reminders_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    """Send every due appointment reminder for `tenant_id` (docs/ROADMAP.md
    Phase 7.3, `product.appointments.reminders.send_due_reminders()`).

    **This endpoint is never called by this product's own code.** No
    scheduled/deferred-job or cross-tenant-enumeration capability exists
    to sanction a self-triggering sweep (see
    `product/appointments/reminders.py`'s own module docstring for the
    two verified SaaS-OS gaps this runs into). It exists for manual/
    testing invocation, or for an external scheduler to call once per
    tenant on a fixed interval using a
    `core.identity.create_service_account()` credential -- an
    already-existing capability, not a new mechanism introduced here.
    """
    result = _call(send_due_reminders, actor_id, tenant_id)
    return {
        "reminded_count": result.reminded_count,
        "appointment_ids": [str(i) for i in result.appointment_ids],
    }


# --- Public, unauthenticated booking/manage -------------------------------------


@router.post("/book/{link_token}", status_code=status.HTTP_201_CREATED)
async def public_book_appointment_route(
    link_token: str, body: PublicBookAppointmentRequest
) -> dict[str, object]:
    """The public booking endpoint (docs/ROADMAP.md Phase 7.2) -- no
    `get_current_actor` dependency, no `tenant_id` in the path (the
    `link_token` resolves it, see `product/appointments/booking.py
    ::resolve_booking_link()`). Rate-limited by `link_token` before
    anything else runs."""
    await _enforce_public_rate_limit(f"appointments_booking:{link_token}")
    return _appointment_dict(
        _call(
            public_book_appointment,
            link_token,
            contact_email=body.contact_email,
            contact_first_name=body.contact_first_name,
            contact_last_name=body.contact_last_name,
            contact_phone=body.contact_phone,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
        )
    )


@router.get("/manage/{manage_token}")
async def public_get_appointment_route(manage_token: str) -> dict[str, object]:
    await _enforce_public_rate_limit(f"appointments_manage:{manage_token}")
    view = resolve_manage_token(manage_token)
    if view is None:
        raise not_found("resource")
    return _appointment_dict(view)


@router.post("/manage/{manage_token}/cancel")
async def public_cancel_appointment_route(manage_token: str) -> dict[str, object]:
    await _enforce_public_rate_limit(f"appointments_manage:{manage_token}")
    return _appointment_dict(_call(public_cancel_appointment, manage_token))


@router.post("/manage/{manage_token}/reschedule")
async def public_reschedule_appointment_route(
    manage_token: str, body: RescheduleAppointmentRequest
) -> dict[str, object]:
    await _enforce_public_rate_limit(f"appointments_manage:{manage_token}")
    return _appointment_dict(
        _call(
            public_reschedule_appointment,
            manage_token,
            new_starts_at=body.new_starts_at,
            new_ends_at=body.new_ends_at,
        )
    )
