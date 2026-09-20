"""Availability-rule CRUD and `compute_available_slots()`'s own
timezone/DST correctness (docs/ROADMAP.md Phase 7.1). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.appointments.availability import (
    MAX_AVAILABILITY_QUERY_DAYS,
    compute_available_slots,
    create_availability_rule,
    delete_availability_rule,
    list_availability_rules,
)
from product.appointments.calendars import create_calendar
from product.appointments.errors import AppointmentValidationError

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _find_dst_transition_date(tz_name: str, year: int) -> date:
    """Derived, not hardcoded: walks every day of `year` in `tz_name`,
    comparing the UTC offset of local noon on consecutive days, and
    returns the first date whose offset differs from the day before --
    a real DST transition date, proven by `zoneinfo` itself rather than
    a manually-calculated calendar assumption baked into this test."""
    tz = ZoneInfo(tz_name)
    cursor = date(year, 1, 1)
    previous_offset = (
        datetime.combine(cursor, datetime.min.time(), tzinfo=tz).replace(hour=12).utcoffset()
    )
    for _ in range(366):
        cursor += timedelta(days=1)
        if cursor.year != year:
            break
        offset = (
            datetime.combine(cursor, datetime.min.time(), tzinfo=tz).replace(hour=12).utcoffset()
        )
        if offset != previous_offset:
            return cursor
        previous_offset = offset
    raise AssertionError(f"{tz_name} has no DST transition in {year}")


def test_availability_rule_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        rule = create_availability_rule(
            owner.id, client.tenant_id, calendar.id, day_of_week=0, start_time=540, end_time=1020
        )
        assert rule.day_of_week == 0

        rules = list_availability_rules(owner.id, client.tenant_id, calendar.id)
        assert any(r.id == rule.id for r in rules)

        delete_availability_rule(owner.id, client.tenant_id, calendar.id, rule.id)
        rules_after = list_availability_rules(owner.id, client.tenant_id, calendar.id)
        assert not any(r.id == rule.id for r in rules_after)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


@pytest.mark.parametrize(
    ("day_of_week", "start_time", "end_time"),
    [(-1, 0, 60), (7, 0, 60), (0, -1, 60), (0, 1440, 1500), (0, 600, 500), (0, 600, 600)],
)
def test_invalid_availability_rule_bounds_rejected(day_of_week, start_time, end_time) -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        with pytest.raises(AppointmentValidationError):
            create_availability_rule(
                owner.id,
                client.tenant_id,
                calendar.id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_dst_transition_produces_different_utc_offset_on_either_side() -> None:
    """The core DST-correctness proof (docs/ROADMAP.md Phase 7's own
    "explicitly distinguish instant vs. local timezone" requirement): the
    identical local 09:00-17:00 rule, applied on either side of a real
    Europe/Amsterdam DST transition, must resolve to a *different* UTC
    instant for the same local wall-clock time -- proving
    `compute_available_slots()` recomputes the offset per-date via
    `zoneinfo`, rather than caching one offset for the whole query range."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id,
            client.tenant_id,
            name="DST Calendar",
            owner_user_id=owner.id,
            timezone="Europe/Amsterdam",
        )
        for dow in range(7):
            create_availability_rule(
                owner.id,
                client.tenant_id,
                calendar.id,
                day_of_week=dow,
                start_time=540,
                end_time=1020,
            )

        transition_date = _find_dst_transition_date("Europe/Amsterdam", 2026)
        before = transition_date - timedelta(days=1)
        after = transition_date + timedelta(days=1)

        slots_before = compute_available_slots(
            owner.id,
            client.tenant_id,
            calendar.id,
            date_from=before,
            date_to=before,
            slot_duration_minutes=60,
        )
        slots_after = compute_available_slots(
            owner.id,
            client.tenant_id,
            calendar.id,
            date_from=after,
            date_to=after,
            slot_duration_minutes=60,
        )
        assert slots_before and slots_after

        first_before_utc_hour = slots_before[0].starts_at.astimezone(UTC).hour
        first_after_utc_hour = slots_after[0].starts_at.astimezone(UTC).hour
        # Same local 09:00 start, but the DST transition shifted the UTC
        # offset by exactly one hour between these two dates.
        assert first_before_utc_hour != first_after_utc_hour
        assert abs(first_before_utc_hour - first_after_utc_hour) == 1

        tz = ZoneInfo("Europe/Amsterdam")
        expected_before = (
            datetime.combine(before, datetime.min.time(), tzinfo=tz).replace(hour=9).astimezone(UTC)
        )
        expected_after = (
            datetime.combine(after, datetime.min.time(), tzinfo=tz).replace(hour=9).astimezone(UTC)
        )
        assert slots_before[0].starts_at == expected_before
        assert slots_after[0].starts_at == expected_after
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_non_european_fixed_offset_timezone_computed_correctly() -> None:
    """A non-European timezone with a non-whole-hour, fixed (no-DST)
    offset -- Asia/Kolkata, UTC+5:30 -- proves the conversion is not
    accidentally assuming whole-hour offsets anywhere in the pipeline."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id,
            client.tenant_id,
            name="Kolkata Calendar",
            owner_user_id=owner.id,
            timezone="Asia/Kolkata",
        )
        for dow in range(7):
            create_availability_rule(
                owner.id,
                client.tenant_id,
                calendar.id,
                day_of_week=dow,
                start_time=600,
                end_time=660,
            )  # local 10:00-11:00

        target_date = date(2026, 6, 15)
        slots = compute_available_slots(
            owner.id,
            client.tenant_id,
            calendar.id,
            date_from=target_date,
            date_to=target_date,
            slot_duration_minutes=60,
        )
        assert len(slots) == 1
        # local 10:00 IST (UTC+5:30) == 04:30 UTC
        expected = datetime(2026, 6, 15, 4, 30, tzinfo=UTC)
        assert slots[0].starts_at == expected
        assert slots[0].ends_at == expected + timedelta(hours=1)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_oversized_date_range_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        with pytest.raises(AppointmentValidationError):
            compute_available_slots(
                owner.id,
                client.tenant_id,
                calendar.id,
                date_from=date(2026, 1, 1),
                date_to=date(2026, 1, 1) + timedelta(days=MAX_AVAILABILITY_QUERY_DAYS + 1),
                slot_duration_minutes=30,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_date_to_before_date_from_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        with pytest.raises(AppointmentValidationError):
            compute_available_slots(
                owner.id,
                client.tenant_id,
                calendar.id,
                date_from=date(2026, 1, 5),
                date_to=date(2026, 1, 1),
                slot_duration_minutes=30,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_existing_confirmed_appointment_is_subtracted_from_available_slots() -> None:
    from product.appointments.booking import book_appointment

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        create_availability_rule(
            owner.id, client.tenant_id, calendar.id, day_of_week=0, start_time=540, end_time=660
        )  # Monday 09:00-11:00 -> two 60-minute slots

        # Find a real upcoming Monday to book against.
        target = date(2026, 1, 5)  # 2026-01-05 is a Monday
        starts_at = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
        book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="slot-taken@example.com",
            contact_first_name="Slot",
            contact_last_name="Taken",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )

        slots = compute_available_slots(
            owner.id,
            client.tenant_id,
            calendar.id,
            date_from=target,
            date_to=target,
            slot_duration_minutes=60,
        )
        slot_starts = [s.starts_at for s in slots]
        assert starts_at not in slot_starts
        assert datetime(2026, 1, 5, 10, 0, tzinfo=UTC) in slot_starts
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
