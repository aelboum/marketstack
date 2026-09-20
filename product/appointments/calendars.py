"""Calendar CRUD and availability-rule CRUD (docs/ROADMAP.md Phase 7.1).

Every function follows the shape established by `product/crm
/companies.py`/`product/marketing/campaigns.py`: authorize via
`product.appointments.permissions.require()` first, then the actual
`tenant_session_scope()` read/write, then `core.audit_log.record()` for
mutations -- metadata carries only identifiers, never a calendar's own
`name` (not PII, but bounded/identifier-only metadata is this product's
uniform discipline regardless).

**`get_or_create_booking_link()`** is the one exception to the
`tenant_session_scope()` shape above: `appointments.booking_links` is
deliberately NOT RLS-scoped (`product/appointments/models.py::BookingLink`'s
own docstring), so once the calendar itself is authorized and resolved
through the ordinary tenant-scoped path, the link row itself is read/
written through a plain, untenanted `infra.db.session_scope()` -- mirrors
`product/marketing/forms.py::create_form()`'s own token-generation shape,
done here as an idempotent get-or-create (rather than always-insert)
since `(tenant_id, calendar_id)` is unique -- one link per calendar
(`product/appointments/models.py::BookingLink`'s own docstring on the
1:1 scope-simplification).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.audit_log import ActorType, AuditOutcome, record
from core.rbac import can
from infra.db import IntegrityError, select, session_scope, tenant_session_scope

from product.appointments.errors import (
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.models import (
    MAX_CALENDAR_NAME_LENGTH,
    MINUTES_PER_DAY,
    BookingLink,
    Calendar,
)
from product.appointments.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.appointments.permissions import CALENDAR_RESOURCE, require

_LINK_TOKEN_BYTES = 32  # matches product/appointments/booking.py's own manage-token byte length


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppointmentValidationError(f"unknown timezone identifier: {timezone!r}") from exc


def _validate_owner_membership(tenant_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    """The real IDOR-adjacent check -- there is no composite FK to fall
    back on (`core.users` is a global table), so this check is the only
    enforcement and must be unconditional.

    **Corrected**: an earlier version of this check used
    `core.identity.get_membership()` (an exact, direct-tenant-only
    lookup) -- which is wrong here for the identical reason
    `docs/ADR/0002-...` already documents for `api.dependencies
    .get_tenant_context()`: an agency owner assigning *themselves* as a
    calendar's owner in one of their own clients has no direct
    `TenantMembership` there, only inherited `SUBTREE` reach, and
    `get_membership()` does not walk the hierarchy. That version rejected
    every legitimate agency-owner-as-calendar-owner case (caught by this
    phase's own `test_agency_owner_reaches_own_clients_calendars_via
    _inherited_subtree` test failing, not assumed). `core.rbac.can()` is
    the correct chokepoint -- it already accounts for both direct
    membership and inherited SUBTREE reach, exactly as every other
    authorization decision in this product goes through it. Checking
    `(CALENDAR_RESOURCE, "read")` is deliberately the lowest bar every
    granted role includes (owner and member both), so this rejects only
    a `owner_user_id` with **no** real relationship to `tenant_id`
    whatsoever -- the actual IDOR case this check exists to catch."""
    if not can(
        actor_id=owner_user_id, tenant_id=tenant_id, action="read", resource=CALENDAR_RESOURCE
    ):
        raise AppointmentReferenceNotFoundError("owner", owner_user_id)


@dataclass(frozen=True, slots=True)
class CalendarView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    owner_user_id: uuid.UUID
    timezone: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: Calendar) -> CalendarView:
    return CalendarView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        owner_user_id=row.owner_user_id,
        timezone=row.timezone,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_calendar(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    owner_user_id: uuid.UUID,
    timezone: str,
) -> CalendarView:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="create")
    if len(name) > MAX_CALENDAR_NAME_LENGTH:
        raise AppointmentValidationError(f"name exceeds {MAX_CALENDAR_NAME_LENGTH} characters.")
    _validate_timezone(timezone)
    _validate_owner_membership(tenant_id, owner_user_id)
    with tenant_session_scope(tenant_id) as session:
        row = Calendar(
            tenant_id=tenant_id, name=name, owner_user_id=owner_user_id, timezone=timezone
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar.create",
        resource_type="appointments.calendar",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_calendar(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_id: uuid.UUID
) -> CalendarView:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Calendar, calendar_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)
        session.expunge(row)
    return _to_view(row)


def list_calendars(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CalendarView]:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Calendar)
                .where(Calendar.tenant_id == tenant_id)
                .order_by(Calendar.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_calendar(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    *,
    name: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    timezone: str | None = None,
) -> CalendarView:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="update")
    if timezone is not None:
        _validate_timezone(timezone)
    if owner_user_id is not None:
        _validate_owner_membership(tenant_id, owner_user_id)
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Calendar, calendar_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)
        if name is not None:
            if len(name) > MAX_CALENDAR_NAME_LENGTH:
                raise AppointmentValidationError(
                    f"name exceeds {MAX_CALENDAR_NAME_LENGTH} characters."
                )
            row.name = name
        if owner_user_id is not None:
            row.owner_user_id = owner_user_id
        if timezone is not None:
            row.timezone = timezone
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar.update",
        resource_type="appointments.calendar",
        resource_id=str(calendar_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_calendar(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_id: uuid.UUID) -> None:
    """No check for existing appointments is performed here -- see
    `product/appointments/models.py`'s own module docstring, "Deletion
    behavior": `appointments.calendar_id` has no `ON DELETE` behavior
    decided (default `RESTRICT`), a disclosed open question for whoever
    adds real calendar-deletion-with-dependents handling. A calendar
    with existing appointments will fail this call with a raw
    `IntegrityError` today -- not silently resolved, not hidden."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Calendar, calendar_id)
        if row is None or row.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.calendar.delete",
        resource_type="appointments.calendar",
        resource_id=str(calendar_id),
        outcome=AuditOutcome.SUCCESS,
    )


def get_or_create_booking_link(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_id: uuid.UUID
) -> str:
    """Returns the calendar's own public `link_token`, creating it on
    first call -- see module docstring. `AppointmentReferenceNotFoundError`
    if `calendar_id` does not resolve in `tenant_id` (the same check
    every other calendar-scoped function here performs, before this
    function ever touches the unscoped `booking_links` table)."""
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        calendar = session.get(Calendar, calendar_id)
        if calendar is None or calendar.tenant_id != tenant_id:
            raise AppointmentReferenceNotFoundError("calendar", calendar_id)

    with session_scope() as session:
        existing = session.execute(
            select(BookingLink).where(
                BookingLink.tenant_id == tenant_id, BookingLink.calendar_id == calendar_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.link_token
        link_token = secrets.token_urlsafe(_LINK_TOKEN_BYTES)
        try:
            session.add(
                BookingLink(link_token=link_token, tenant_id=tenant_id, calendar_id=calendar_id)
            )
            session.flush()
        except IntegrityError:
            # A concurrent caller for the same calendar_id won the
            # UniqueConstraint(tenant_id, calendar_id) race between the
            # SELECT above and this INSERT -- re-fetch and return the
            # winner's row rather than surfacing a raw IntegrityError for
            # what is, from either caller's perspective, a successful
            # get-or-create.
            session.rollback()
            winner = session.execute(
                select(BookingLink).where(
                    BookingLink.tenant_id == tenant_id, BookingLink.calendar_id == calendar_id
                )
            ).scalar_one()
            return winner.link_token
        return link_token


__all__ = [
    "MINUTES_PER_DAY",
    "CalendarView",
    "create_calendar",
    "delete_calendar",
    "get_calendar",
    "get_or_create_booking_link",
    "list_calendars",
    "update_calendar",
]
