"""`FakeCalendarProvider` round-trips through `CalendarProvider` correctly
(docs/ROADMAP.md Phase 7.4). No database, no network -- a plain unit
test, part of the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from product.appointments.calendar_sync import (
    CalendarProvider,
    CalendarSyncError,
    ExternalCalendarChange,
    FakeCalendarProvider,
)


def test_fake_calendar_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeCalendarProvider(), CalendarProvider)


def test_sync_booking_round_trips() -> None:
    provider = FakeCalendarProvider()
    appointment_id = uuid.uuid4()
    starts_at = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    ends_at = starts_at + timedelta(hours=1)

    result = provider.sync_booking(appointment_id, starts_at, ends_at)

    assert result.accepted is True
    assert result.external_event_id == "fake-1"
    assert provider.synced == [(appointment_id, starts_at, ends_at)]


def test_sync_booking_raises_calendar_sync_error_when_configured_to_fail() -> None:
    provider = FakeCalendarProvider(fail=True)
    with pytest.raises(CalendarSyncError):
        provider.sync_booking(uuid.uuid4(), datetime.now(UTC), datetime.now(UTC))


def test_pull_external_changes_returns_only_seeded_changes_since_the_given_instant() -> None:
    provider = FakeCalendarProvider()
    calendar_id = uuid.uuid4()
    since = datetime(2026, 6, 1, tzinfo=UTC)
    old_change = ExternalCalendarChange(
        external_event_id="old",
        starts_at=since - timedelta(days=1),
        ends_at=since - timedelta(days=1) + timedelta(hours=1),
    )
    new_change = ExternalCalendarChange(
        external_event_id="new",
        starts_at=since + timedelta(days=1),
        ends_at=since + timedelta(days=1) + timedelta(hours=1),
    )
    provider.seed_external_change(calendar_id, old_change)
    provider.seed_external_change(calendar_id, new_change)

    changes = provider.pull_external_changes(calendar_id, since)

    assert changes == [new_change]


def test_pull_external_changes_raises_calendar_sync_error_when_configured_to_fail() -> None:
    provider = FakeCalendarProvider(fail=True)
    with pytest.raises(CalendarSyncError):
        provider.pull_external_changes(uuid.uuid4(), datetime.now(UTC))
