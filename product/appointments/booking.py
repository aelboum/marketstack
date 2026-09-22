"""Booking, rescheduling, cancellation -- authenticated and public
(docs/ROADMAP.md Phase 7.2).

**Double-booking prevention is the database's job, not this module's**:
every booking/reschedule attempt below simply performs the write and
catches `infra.db.IntegrityError` -- the real safety net is the
`EXCLUDE USING gist (calendar_id WITH =, time_range WITH &&) WHERE
(status = 'confirmed')` constraint declared in migration
`0026_create_appointments_appointments_table` (see `product/appointments
/models.py`'s own module docstring for the full mechanics). This module
never attempts a "check then insert" as its own safety guarantee --
`product/appointments/availability.py::compute_available_slots()` is a
courtesy/UX answer for what a caller should try, not what makes a
double-booking structurally impossible; catching the constraint
violation here is what actually does.

**Reuses `product.crm.contacts.create_or_update_contact_from_trusted_source()`
directly, never a second anonymous-contact-creation path** -- the same
function `product/marketing/forms.py::submit_form()` already calls, for
the identical "trusts its caller" reasoning
(`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`).

**`book_appointment()` is the one function both the public and
authenticated booking paths funnel through** -- `actor_user_id=None`
means the public path (audited as `ActorType.SYSTEM`, mirroring
`create_or_update_contact_from_trusted_source()`'s own established
dispatch); a real `actor_user_id` means an authenticated staff member
booked on a contact's behalf (audited as `ActorType.USER`).

**Public token resolution** (`resolve_booking_link()`/
`resolve_manage_token()`) mirrors `product/marketing/forms.py
::resolve_form_by_token()`/`product/white_label/domains.py
::resolve_tenant_for_domain()` exactly: a plain, untenanted
`infra.db.session_scope()` read against `BookingLink`/
`AppointmentManageToken` -- see `product/appointments/models.py`'s own
docstrings on those two classes for why they are separate, unscoped
tables rather than columns on the RLS-protected `Calendar`/`Appointment`
tables.

**Public cancel/reschedule are rate-limited and non-enumerating, the
identical treatment `product/marketing/forms.py::submit_form()` gives
the public form-submission endpoint** -- these are real mutations on a
real resource (unlike the read-only, idempotent tracking pixel/click
routes in `product/marketing/tracking.py`, which are deliberately NOT
rate-limited and NEVER 404), so they get the stricter treatment, not the
looser one. See `product/appointments/routes.py` for where the rate
limit is actually enforced (mirroring `product/marketing/routes.py
::_enforce_public_rate_limit()`'s exact shape).

**Cancel-vs-reschedule races on the same appointment are serialized with
a real row lock** (`session.get(Appointment, id, with_for_update=True)`)
-- two concurrent state-changing operations on the identical row cannot
interleave into a torn state; Postgres's own row lock makes the loser
wait for the winner's transaction to commit, then re-read the
now-current row, exactly the guarantee `docs/ROADMAP.md` Phase 7's own
"cancellation races"/"rescheduling races" requirement calls for.

`book_appointment()` publishes `appointments.appointment.booked`
(docs/ROADMAP.md Phase 10.2's own trigger library) -- a single, additive
`publish()` call added in this phase, mirroring `product/crm/opportunities.py
::change_stage()`'s own precedent; no other behavior in this module
changed for it.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, session_scope, tenant_session_scope

from product.appointments.errors import (
    AppointmentReferenceNotFoundError,
    AppointmentSlotUnavailableError,
    AppointmentTokenInvalidError,
    AppointmentValidationError,
)
from product.appointments.models import (
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    Appointment,
    AppointmentManageToken,
    BookingLink,
    Calendar,
)
from product.appointments.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.appointments.permissions import APPOINTMENT_RESOURCE, require
from product.crm.contacts import create_or_update_contact_from_trusted_source
from product.foundation.events import Event, publish

APPOINTMENT_BOOKED_EVENT_TYPE = "appointments.appointment.booked"
APPOINTMENT_BOOKED_EVENT_VERSION = 1

_TOKEN_BYTES = 32  # mirrors core/identity/service.py's own invitation-token byte length


@dataclass(frozen=True, slots=True)
class AppointmentView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    calendar_id: uuid.UUID
    contact_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    status: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: Appointment) -> AppointmentView:
    return AppointmentView(
        id=row.id,
        tenant_id=row.tenant_id,
        calendar_id=row.calendar_id,
        contact_id=row.contact_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_time_range(starts_at: datetime, ends_at: datetime) -> None:
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise AppointmentValidationError("starts_at/ends_at must be timezone-aware.")
    if ends_at <= starts_at:
        raise AppointmentValidationError("ends_at must be after starts_at.")


def book_appointment(
    *,
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    contact_email: str,
    contact_first_name: str,
    contact_last_name: str,
    contact_phone: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
    actor_user_id: uuid.UUID | None = None,
) -> AppointmentView:
    """The shared core booking function -- see module docstring. Raises
    `AppointmentSlotUnavailableError` if the requested slot collides with
    an existing `'confirmed'` appointment on `calendar_id` (the real,
    database-enforced `EXCLUDE` constraint), `AppointmentReferenceNotFoundError`
    if `calendar_id` does not resolve in `tenant_id`."""
    _validate_time_range(starts_at, ends_at)

    contact = create_or_update_contact_from_trusted_source(
        tenant_id,
        email=contact_email,
        first_name=contact_first_name,
        last_name=contact_last_name,
        phone=contact_phone,
        source=f"appointments:calendar:{calendar_id}",
    )

    manage_token = secrets.token_urlsafe(_TOKEN_BYTES)
    try:
        with tenant_session_scope(tenant_id) as session:
            calendar = session.get(Calendar, calendar_id)
            if calendar is None or calendar.tenant_id != tenant_id:
                raise AppointmentReferenceNotFoundError("calendar", calendar_id)
            row = Appointment(
                tenant_id=tenant_id,
                calendar_id=calendar_id,
                contact_id=contact.id,
                starts_at=starts_at,
                ends_at=ends_at,
                status=STATUS_CONFIRMED,
            )
            session.add(row)
            session.flush()
            session.add(
                AppointmentManageToken(
                    manage_token=manage_token, tenant_id=tenant_id, appointment_id=row.id
                )
            )
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        raise AppointmentSlotUnavailableError(calendar_id) from exc

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER if actor_user_id is not None else ActorType.SYSTEM,
        actor_user_id=actor_user_id,
        action="appointments.appointment.book",
        resource_type="appointments.appointment",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        # Identifiers/timestamps only -- never the contact's name/email/
        # phone, per docs/ROADMAP.md Phase 7's own PII/audit requirement.
        metadata={
            "calendar_id": str(calendar_id),
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        },
    )
    publish(
        Event(
            type=APPOINTMENT_BOOKED_EVENT_TYPE,
            version=APPOINTMENT_BOOKED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "appointment_id": str(row.id),
                "calendar_id": str(calendar_id),
                "contact_id": str(contact.id),
            },
        )
    )
    return _to_view(row)


# --- Public, unauthenticated booking -----------------------------------------


@dataclass(frozen=True, slots=True)
class BookingLinkView:
    tenant_id: uuid.UUID
    calendar_id: uuid.UUID


def resolve_booking_link(link_token: str) -> BookingLinkView | None:
    if not link_token:
        return None
    with session_scope() as session:
        row = session.get(BookingLink, link_token)
        if row is None:
            return None
        return BookingLinkView(tenant_id=row.tenant_id, calendar_id=row.calendar_id)


def public_book_appointment(
    link_token: str,
    *,
    contact_email: str,
    contact_first_name: str,
    contact_last_name: str,
    contact_phone: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
) -> AppointmentView:
    link = resolve_booking_link(link_token)
    if link is None:
        raise AppointmentTokenInvalidError(f"unknown booking link token: {link_token!r}")
    return book_appointment(
        tenant_id=link.tenant_id,
        calendar_id=link.calendar_id,
        contact_email=contact_email,
        contact_first_name=contact_first_name,
        contact_last_name=contact_last_name,
        contact_phone=contact_phone,
        starts_at=starts_at,
        ends_at=ends_at,
        actor_user_id=None,
    )


def resolve_manage_token(manage_token: str) -> AppointmentView | None:
    if not manage_token:
        return None
    with session_scope() as session:
        mapping = session.get(AppointmentManageToken, manage_token)
        if mapping is None:
            return None
        tenant_id, appointment_id = mapping.tenant_id, mapping.appointment_id
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Appointment, appointment_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        session.expunge(row)
    return _to_view(row)


def _locked_appointment_for_manage_token(session, manage_token: str) -> Appointment:
    """Resolves `manage_token` to its real tenant/appointment (untenanted
    lookup, see module docstring), then re-reads the appointment row
    **under a row lock**, inside `session`'s own `tenant_session_scope()`
    -- the serialization point for the cancel-vs-reschedule race (module
    docstring)."""
    with session_scope() as lookup_session:
        mapping = lookup_session.get(AppointmentManageToken, manage_token)
        if mapping is None:
            raise AppointmentTokenInvalidError(f"unknown manage token: {manage_token!r}")
        tenant_id, appointment_id = mapping.tenant_id, mapping.appointment_id
    row = session.get(Appointment, appointment_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise AppointmentTokenInvalidError(f"unknown manage token: {manage_token!r}")
    return row


def _resolve_tenant_for_manage_token(manage_token: str) -> uuid.UUID:
    with session_scope() as session:
        mapping = session.get(AppointmentManageToken, manage_token)
        if mapping is None:
            raise AppointmentTokenInvalidError(f"unknown manage token: {manage_token!r}")
        return mapping.tenant_id


def public_cancel_appointment(manage_token: str) -> AppointmentView:
    tenant_id = _resolve_tenant_for_manage_token(manage_token)
    with tenant_session_scope(tenant_id) as session:
        row = _locked_appointment_for_manage_token(session, manage_token)
        if row.status == STATUS_CANCELLED:
            raise AppointmentValidationError(f"appointment {row.id} is already cancelled.")
        row.status = STATUS_CANCELLED
        session.flush()
        session.refresh(row)
        appointment_id = row.id
        calendar_id = row.calendar_id
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action="appointments.appointment.cancel",
        resource_type="appointments.appointment",
        resource_id=str(appointment_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"calendar_id": str(calendar_id)},
    )
    return _to_view(row)


def public_reschedule_appointment(
    manage_token: str, *, new_starts_at: datetime, new_ends_at: datetime
) -> AppointmentView:
    _validate_time_range(new_starts_at, new_ends_at)
    tenant_id = _resolve_tenant_for_manage_token(manage_token)
    try:
        with tenant_session_scope(tenant_id) as session:
            row = _locked_appointment_for_manage_token(session, manage_token)
            # Captured before the mutating flush below -- if the flush
            # raises IntegrityError (the EXCLUDE constraint), the except
            # clause below still needs a real calendar_id to report.
            calendar_id = row.calendar_id
            if row.status != STATUS_CONFIRMED:
                raise AppointmentValidationError(
                    f"appointment {row.id} cannot be rescheduled while "
                    f"status={row.status!r} (only 'confirmed' appointments can be)."
                )
            row.starts_at = new_starts_at
            row.ends_at = new_ends_at
            session.flush()
            session.refresh(row)
            appointment_id = row.id
            session.expunge(row)
    except IntegrityError as exc:
        raise AppointmentSlotUnavailableError(calendar_id) from exc

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action="appointments.appointment.reschedule",
        resource_type="appointments.appointment",
        resource_id=str(appointment_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "calendar_id": str(calendar_id),
            "starts_at": new_starts_at.isoformat(),
            "ends_at": new_ends_at.isoformat(),
        },
    )
    return _to_view(row)


# --- Authenticated staff read -------------------------------------------------


def list_appointments(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[AppointmentView]:
    """The staff-facing appointment list this module never had (Phase 28
    "Command Center" audit finding: no authenticated way existed to list
    appointments at all -- an appointment was only ever visible through
    the public manage-token read, or as the direct return value of
    booking/cancel/reschedule). Mirrors `list_calendars()`'s own shape
    exactly. `starts_after`/`starts_before` are optional, inclusive-lower/
    exclusive-upper bounds on `Appointment.starts_at` -- e.g. "today's
    appointments" is `starts_after=<midnight local>,
    starts_before=<next midnight local>`; the caller resolves "today" in
    its own timezone, this function does no timezone reasoning of its
    own, mirroring `_validate_time_range()`'s own "the caller sends
    timezone-aware datetimes" contract. Ordered chronologically
    (`starts_at` ascending, not `created_at` descending like every other
    list in this module) -- the only sensible reading order for "what's
    coming up," not "what was most recently created."
    """
    require(actor_user_id, tenant_id, resource=APPOINTMENT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        stmt = select(Appointment).where(Appointment.tenant_id == tenant_id)
        if starts_after is not None:
            stmt = stmt.where(Appointment.starts_at >= starts_after)
        if starts_before is not None:
            stmt = stmt.where(Appointment.starts_at < starts_before)
        rows = (
            session.execute(
                stmt.order_by(Appointment.starts_at.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


# --- Authenticated staff cancel/reschedule -----------------------------------


def staff_cancel_appointment(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, appointment_id: uuid.UUID
) -> AppointmentView:
    require(actor_user_id, tenant_id, resource=APPOINTMENT_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Appointment, appointment_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("appointment", appointment_id)
        if row.status == STATUS_CANCELLED:
            raise AppointmentValidationError(f"appointment {row.id} is already cancelled.")
        row.status = STATUS_CANCELLED
        session.flush()
        session.refresh(row)
        calendar_id = row.calendar_id
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.appointment.cancel",
        resource_type="appointments.appointment",
        resource_id=str(appointment_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"calendar_id": str(calendar_id)},
    )
    return _to_view(row)


def staff_reschedule_appointment(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID,
    *,
    new_starts_at: datetime,
    new_ends_at: datetime,
) -> AppointmentView:
    require(actor_user_id, tenant_id, resource=APPOINTMENT_RESOURCE, action="update")
    _validate_time_range(new_starts_at, new_ends_at)
    try:
        with tenant_session_scope(tenant_id) as session:
            row = session.get(Appointment, appointment_id, with_for_update=True)
            if row is None or row.tenant_id != tenant_id:
                raise AppointmentReferenceNotFoundError("appointment", appointment_id)
            calendar_id = row.calendar_id
            if row.status != STATUS_CONFIRMED:
                raise AppointmentValidationError(
                    f"appointment {row.id} cannot be rescheduled while "
                    f"status={row.status!r} (only 'confirmed' appointments can be)."
                )
            row.starts_at = new_starts_at
            row.ends_at = new_ends_at
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        raise AppointmentSlotUnavailableError(calendar_id) from exc

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.appointment.reschedule",
        resource_type="appointments.appointment",
        resource_id=str(appointment_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "calendar_id": str(calendar_id),
            "starts_at": new_starts_at.isoformat(),
            "ends_at": new_ends_at.isoformat(),
        },
    )
    return _to_view(row)


__all__ = [
    "AppointmentView",
    "BookingLinkView",
    "book_appointment",
    "list_appointments",
    "public_book_appointment",
    "public_cancel_appointment",
    "public_reschedule_appointment",
    "resolve_booking_link",
    "resolve_manage_token",
    "staff_cancel_appointment",
    "staff_reschedule_appointment",
]
