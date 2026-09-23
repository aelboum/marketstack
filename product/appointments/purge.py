"""Tenant purge participants for the `appointments` schema (mirrors
`product/marketing/purge.py`'s proven two-participant pattern). Registered
from `product/api/main.py::create_app()`.

**Two participants, not one** -- identical reason to `product/marketing
/purge.py`'s own docstring:

- `AppointmentsDataPurgeParticipant` covers every ordinary, RLS-scoped
  `appointments.*` table (`calendar_events`, `appointments`,
  `availability_rules`, `calendars`) via the normal `tenant_session_scope()`
  path. Deletion order: leaves (`calendar_events`, `appointments`,
  `availability_rules`) before the root (`calendars`) -- correct
  regardless of what `ON DELETE` behavior each individual FK happens to
  carry, defense-in-depth (see `product/appointments/models.py`'s own
  module docstring on `appointments.calendar_id` having no `ON DELETE`
  decided -- purge order must not depend on it). `calendar_events` goes
  first of all: it references both `calendars` (same undecided-`RESTRICT`
  shape) and `appointments` (`SET NULL`, order-independent).
- `AppointmentsUnscopedDataPurgeParticipant` covers `booking_links` and
  `appointment_manage_tokens` -- deliberately NOT RLS-scoped (see
  `product/appointments/models.py`'s own docstrings on `BookingLink`/
  `AppointmentManageToken`), so this participant reads through a plain
  `session_scope()` with an explicit `tenant_id` filter instead, mirroring
  `product/marketing/purge.py::MarketingUnscopedDataPurgeParticipant`'s
  identical pattern. An orphaned booking link or manage token pointing at
  a purged tenant would otherwise silently keep resolving to a tenant
  that no longer principally exists.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, session_scope, tenant_session_scope

from product.appointments.models import (
    Appointment,
    AppointmentManageToken,
    AvailabilityRule,
    BookingLink,
    Calendar,
    CalendarEvent,
)

_SCOPED_PURGE_ORDER = (
    # CalendarEvent first -- it references both Appointment (SET NULL,
    # order-independent) and Calendar (no ON DELETE decided, RESTRICT by
    # default), so it must be gone before Calendar regardless.
    CalendarEvent,
    Appointment,
    AvailabilityRule,
    Calendar,
)

_UNSCOPED_PURGE_ORDER = (
    AppointmentManageToken,
    BookingLink,
)


class AppointmentsDataPurgeParticipant:
    """Deletes every ordinary, RLS-scoped `appointments.*` row belonging
    to the tenant being purged, in dependency order. Idempotent -- a
    second call finds nothing left in any table and deletes zero rows,
    never an error."""

    @property
    def name(self) -> str:
        return "appointments.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            for model in _SCOPED_PURGE_ORDER:
                rows = (
                    session.execute(
                        select(model).where(model.tenant_id == tenant_id).with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    session.delete(row)
                session.flush()


class AppointmentsUnscopedDataPurgeParticipant:
    """Deletes every `appointments.booking_links`/
    `appointments.appointment_manage_tokens` row mapped to the tenant
    being purged. Idempotent. Uses a plain, untenanted `session_scope()`
    with an explicit `tenant_id` filter -- these two tables carry no RLS
    policy to rely on instead (see module docstring)."""

    @property
    def name(self) -> str:
        return "appointments.unscoped"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with session_scope() as session:
            for model in _UNSCOPED_PURGE_ORDER:
                rows = (
                    session.execute(
                        select(model).where(model.tenant_id == tenant_id).with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    session.delete(row)
                session.flush()


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See `product/crm/purge.py::register()`'s own docstring for the
    re-registration/idempotency reasoning, applied here to both
    participants."""
    active_registry = registry if registry is not None else default_registry()
    for participant in (
        AppointmentsDataPurgeParticipant(),
        AppointmentsUnscopedDataPurgeParticipant(),
    ):
        try:
            active_registry.register(participant)
        except DuplicateTenantPurgeParticipantError:
            if not any(
                isinstance(p, type(participant)) for p in active_registry.list()
            ):  # pragma: no cover -- would mean a *different* type reused this name
                raise
