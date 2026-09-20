"""Calendar provider sync interface -- deliberately PARTIAL
(docs/ROADMAP.md Phase 7.4).

Mirrors `core/email/provider.py::EmailProvider`/`FakeEmailProvider`'s
exact shape: a `@runtime_checkable Protocol` plus one real, in-memory
`Fake*` implementation of it -- not a mock, a genuine implementation
useful on its own for tests.

**Explicit scope boundary -- this phase ships the interface and a fake
only.** No vendor was selected for this phase, so this module never
invents one, never contains real OAuth, never touches `infra.secrets`,
and never makes a real HTTP call. It is also not wired into
`product/appointments/booking.py`'s real booking flow -- no route, no
service function anywhere else in this package calls
`CalendarProvider.sync_booking()`/`pull_external_changes()` today. This
is the provider-neutral seam a real integration (Google Calendar,
Microsoft Graph, CalDAV, ...) would be built behind, once one is
actually selected -- deliberately not built further than that seam this
phase.

**No conflict-resolution logic exists here, disclosed, not hidden.**
`pull_external_changes()` returns whatever the provider reports changed;
reconciling that against this product's own `Appointment` rows (what
happens on a double-edit, which side wins, whether a partial sync can
leave inconsistent state) is unimplemented -- a real integration would
need to design and test that explicitly before this interface could be
safely wired into the real booking flow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SyncResult:
    """The one normalized outcome every `CalendarProvider.sync_booking()`
    call returns -- never a provider-specific response object, mirroring
    `core.email.provider.EmailSendResult`'s identical role."""

    accepted: bool
    external_event_id: str | None = None


@dataclass(frozen=True)
class ExternalCalendarChange:
    """One change a provider reports for `pull_external_changes()` --
    deliberately minimal (an external event id and whether it was
    deleted); no field for this product's own `Appointment.id` since
    reconciling the two is exactly the unimplemented conflict-resolution
    logic this module's own docstring discloses."""

    external_event_id: str
    starts_at: datetime
    ends_at: datetime
    deleted: bool = False


@runtime_checkable
class CalendarProvider(Protocol):
    """The two provider-side operations a partial calendar-sync seam
    needs: push one local booking outward, and pull whatever the
    external calendar reports changed since a given instant. Deliberately
    smaller than a real two-way sync would need -- see module docstring's
    disclosed conflict-resolution boundary."""

    def sync_booking(
        self, appointment_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> SyncResult:
        """Push one local booking to the external calendar. Must raise
        `CalendarSyncError` (never a raw provider/transport exception) on
        failure."""
        ...

    def pull_external_changes(
        self, calendar_id: uuid.UUID, since: datetime
    ) -> list[ExternalCalendarChange]:
        """Return every change the external calendar reports for
        `calendar_id` since `since`. No pagination/cursor concept exists
        here -- a real provider integration would need one; this fake
        does not, since it never holds more than a test asserts against
        directly."""
        ...


class CalendarSyncError(Exception):
    """Raised by a real `CalendarProvider` implementation on any
    provider/transport failure -- never a raw provider-specific
    exception, mirroring `core.email.errors.EmailProviderError`'s
    identical role. `FakeCalendarProvider` raises this when configured
    to fail, exactly as `FakeEmailProvider` does for `EmailProviderError`."""


class FakeCalendarProvider:
    """An in-memory `CalendarProvider` -- no network access, no
    credentials, no OAuth. Records every booking it was asked to sync and
    lets a test seed external changes for `pull_external_changes()` to
    return, mirroring `core.email.provider.FakeEmailProvider`'s identical
    role for `EmailProvider`."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.synced: list[tuple[uuid.UUID, datetime, datetime]] = []
        self.external_changes: dict[uuid.UUID, list[ExternalCalendarChange]] = {}

    def sync_booking(
        self, appointment_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> SyncResult:
        if self.fail:
            raise CalendarSyncError("FakeCalendarProvider configured to fail")
        self.synced.append((appointment_id, starts_at, ends_at))
        return SyncResult(accepted=True, external_event_id=f"fake-{len(self.synced)}")

    def pull_external_changes(
        self, calendar_id: uuid.UUID, since: datetime
    ) -> list[ExternalCalendarChange]:
        if self.fail:
            raise CalendarSyncError("FakeCalendarProvider configured to fail")
        return [
            change
            for change in self.external_changes.get(calendar_id, [])
            if change.starts_at >= since
        ]

    def seed_external_change(self, calendar_id: uuid.UUID, change: ExternalCalendarChange) -> None:
        """Test-only helper -- lets a test populate what
        `pull_external_changes()` returns without a real external
        calendar to poll."""
        self.external_changes.setdefault(calendar_id, []).append(change)


__all__ = [
    "CalendarProvider",
    "CalendarSyncError",
    "ExternalCalendarChange",
    "FakeCalendarProvider",
    "SyncResult",
]
