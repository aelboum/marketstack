"""Availability-rule CRUD and availability computation (docs/ROADMAP.md
Phase 7.1's own core acceptance criterion: "availability correctly
reflects configured rules and existing bookings").

**`day_of_week`**: `0` = Monday .. `6` = Sunday, matching Python's own
`datetime.date.weekday()` convention exactly (so no translation table is
needed anywhere this value is produced or consumed).

**`compute_available_slots()` is the one function in this module that
actually does timezone-aware work, and it is the answer to `docs/ROADMAP.md`
Phase 7's own explicit "explicitly distinguish instant in time vs.
business/local timezone" and DST requirements**: `AvailabilityRule.start_time`
/`end_time` are local wall-clock minutes-since-midnight
(`product/appointments/models.py`'s own module docstring) -- for a
*specific calendar date*, this function combines that local time with the
date, attaches the calendar's own `zoneinfo.ZoneInfo(timezone)`, and lets
Python's `zoneinfo` resolve the correct UTC offset for that exact date --
which is what makes a "9am-5pm every Monday" rule automatically produce a
different UTC instant on either side of a DST transition, with no special
casing in this function itself (the correctness lives entirely in using
`zoneinfo` per-date rather than a single cached offset). Existing
`'confirmed'` appointments are subtracted via an ordinary, tenant-scoped
query over `starts_at`/`ends_at` (both already canonical UTC) -- **not**
the database `EXCLUDE` constraint, which is the write-time safety net,
never the read-time availability answer a caller sees before attempting
to book (`product/appointments/models.py`'s own module docstring makes
the identical distinction).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.appointments.errors import (
    AppointmentReferenceNotFoundError,
    AppointmentValidationError,
)
from product.appointments.models import (
    MINUTES_PER_DAY,
    Appointment,
    AvailabilityRule,
    Calendar,
)
from product.appointments.permissions import CALENDAR_RESOURCE, require

# A generous but real bound -- computing slots for an unbounded date
# range would be an unbounded-work API surface (docs/ROADMAP.md Phase 7's
# own "bounded date-range size" requirement).
MAX_AVAILABILITY_QUERY_DAYS = 90
MIN_SLOT_DURATION_MINUTES = 5
MAX_SLOT_DURATION_MINUTES = MINUTES_PER_DAY


@dataclass(frozen=True, slots=True)
class AvailabilityRuleView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    calendar_id: uuid.UUID
    day_of_week: int
    start_time: int
    end_time: int
    created_at: datetime


def _rule_to_view(row: AvailabilityRule) -> AvailabilityRuleView:
    return AvailabilityRuleView(
        id=row.id,
        tenant_id=row.tenant_id,
        calendar_id=row.calendar_id,
        day_of_week=row.day_of_week,
        start_time=row.start_time,
        end_time=row.end_time,
        created_at=row.created_at,
    )


def _require_calendar(session, tenant_id: uuid.UUID, calendar_id: uuid.UUID) -> Calendar:
    calendar = session.get(Calendar, calendar_id)
    if calendar is None or calendar.tenant_id != tenant_id:
        raise AppointmentReferenceNotFoundError("calendar", calendar_id)
    return calendar


def create_availability_rule(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    *,
    day_of_week: int,
    start_time: int,
    end_time: int,
) -> AvailabilityRuleView:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="update")
    if not (0 <= day_of_week <= 6):
        raise AppointmentValidationError("day_of_week must be between 0 (Monday) and 6 (Sunday).")
    if not (0 <= start_time < MINUTES_PER_DAY):
        raise AppointmentValidationError(f"start_time must be in [0, {MINUTES_PER_DAY}).")
    if not (0 < end_time <= MINUTES_PER_DAY):
        raise AppointmentValidationError(f"end_time must be in (0, {MINUTES_PER_DAY}].")
    if end_time <= start_time:
        raise AppointmentValidationError("end_time must be after start_time.")
    with tenant_session_scope(tenant_id) as session:
        _require_calendar(session, tenant_id, calendar_id)
        row = AvailabilityRule(
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.availability_rule.create",
        resource_type="appointments.availability_rule",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"calendar_id": str(calendar_id)},
    )
    return _rule_to_view(row)


def list_availability_rules(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_id: uuid.UUID
) -> list[AvailabilityRuleView]:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        _require_calendar(session, tenant_id, calendar_id)
        rows = (
            session.execute(
                select(AvailabilityRule)
                .where(
                    AvailabilityRule.tenant_id == tenant_id,
                    AvailabilityRule.calendar_id == calendar_id,
                )
                .order_by(AvailabilityRule.day_of_week.asc(), AvailabilityRule.start_time.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_rule_to_view(row) for row in rows]


def delete_availability_rule(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, calendar_id: uuid.UUID, rule_id: uuid.UUID
) -> None:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(AvailabilityRule, rule_id)
        if row is None or row.tenant_id != tenant_id or row.calendar_id != calendar_id:
            raise AppointmentReferenceNotFoundError("availability_rule", rule_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.availability_rule.delete",
        resource_type="appointments.availability_rule",
        resource_id=str(rule_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"calendar_id": str(calendar_id)},
    )


@dataclass(frozen=True, slots=True)
class AvailableSlot:
    starts_at: datetime
    ends_at: datetime


def compute_available_slots(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    calendar_id: uuid.UUID,
    *,
    date_from: date,
    date_to: date,
    slot_duration_minutes: int,
) -> list[AvailableSlot]:
    require(actor_user_id, tenant_id, resource=CALENDAR_RESOURCE, action="read")
    if date_to < date_from:
        raise AppointmentValidationError("date_to must not be before date_from.")
    if (date_to - date_from).days > MAX_AVAILABILITY_QUERY_DAYS:
        raise AppointmentValidationError(f"date range exceeds {MAX_AVAILABILITY_QUERY_DAYS} days.")
    if not (MIN_SLOT_DURATION_MINUTES <= slot_duration_minutes <= MAX_SLOT_DURATION_MINUTES):
        raise AppointmentValidationError(
            f"slot_duration_minutes must be in "
            f"[{MIN_SLOT_DURATION_MINUTES}, {MAX_SLOT_DURATION_MINUTES}]."
        )

    with tenant_session_scope(tenant_id) as session:
        calendar = _require_calendar(session, tenant_id, calendar_id)
        tz = ZoneInfo(calendar.timezone)
        rules = (
            session.execute(
                select(AvailabilityRule).where(
                    AvailabilityRule.tenant_id == tenant_id,
                    AvailabilityRule.calendar_id == calendar_id,
                )
            )
            .scalars()
            .all()
        )
        rules_by_day: dict[int, list[AvailabilityRule]] = {}
        for rule in rules:
            # Expunged here, before this `with` block (and its session)
            # closes -- these rows are read again below (`rule.start_time`/
            # `rule.end_time`), outside the session scope, in the per-date
            # slot-generation loop. Without this, SQLAlchemy's expire-on-
            # commit behavior can invalidate the row's loaded attributes
            # when the transaction closes, and the later access then tries
            # to lazily reload from a session that no longer exists --
            # DetachedInstanceError (caught by this function's own DST/
            # timezone tests failing, not assumed). Mirrors
            # `list_availability_rules()`'s own correct per-row expunge.
            session.expunge(rule)
            rules_by_day.setdefault(rule.day_of_week, []).append(rule)

        # A generous UTC window covering the whole local date range,
        # regardless of the calendar's own offset -- existing bookings
        # are compared against real UTC instants below, never re-derived
        # from local time.
        window_start = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(UTC) - timedelta(
            days=1
        )
        window_end = datetime.combine(date_to, time.max, tzinfo=tz).astimezone(UTC) + timedelta(
            days=1
        )
        existing = (
            session.execute(
                select(Appointment).where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.calendar_id == calendar_id,
                    Appointment.status == "confirmed",
                    Appointment.starts_at < window_end,
                    Appointment.ends_at > window_start,
                )
            )
            .scalars()
            .all()
        )
        booked_ranges = [(a.starts_at, a.ends_at) for a in existing]

    slots: list[AvailableSlot] = []
    slot_delta = timedelta(minutes=slot_duration_minutes)
    current_date = date_from
    while current_date <= date_to:
        for rule in rules_by_day.get(current_date.weekday(), []):
            # Per-date construction with the calendar's own zoneinfo --
            # this is what makes the resulting UTC offset correct across
            # a DST transition: the same local start_time/end_time
            # produces a different UTC instant depending on which side of
            # the transition `current_date` falls on. See module
            # docstring.
            local_start = datetime.combine(
                current_date,
                time(hour=rule.start_time // 60, minute=rule.start_time % 60),
                tzinfo=tz,
            )
            if rule.end_time == MINUTES_PER_DAY:
                local_end = datetime.combine(current_date, time.max, tzinfo=tz) + timedelta(
                    microseconds=1
                )
            else:
                local_end = datetime.combine(
                    current_date,
                    time(hour=rule.end_time // 60, minute=rule.end_time % 60),
                    tzinfo=tz,
                )

            cursor = local_start
            while cursor + slot_delta <= local_end:
                slot_start_utc = cursor.astimezone(UTC)
                slot_end_utc = (cursor + slot_delta).astimezone(UTC)
                overlaps_existing = any(
                    slot_start_utc < b_end and slot_end_utc > b_start
                    for b_start, b_end in booked_ranges
                )
                if not overlaps_existing:
                    slots.append(AvailableSlot(starts_at=slot_start_utc, ends_at=slot_end_utc))
                cursor += slot_delta
        current_date += timedelta(days=1)

    slots.sort(key=lambda s: s.starts_at)
    return slots


__all__ = [
    "MAX_AVAILABILITY_QUERY_DAYS",
    "MAX_SLOT_DURATION_MINUTES",
    "MIN_SLOT_DURATION_MINUTES",
    "AvailabilityRuleView",
    "AvailableSlot",
    "compute_available_slots",
    "create_availability_rule",
    "delete_availability_rule",
    "list_availability_rules",
]
