"""ORM models for the `appointments` schema (docs/ROADMAP.md Phase
7.1-7.2).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like `product/crm/models.py`/`product/marketing
/models.py` -- this module never imports `sqlalchemy` directly. `infra.db`
exports no `Time` column type, so `AvailabilityRule.start_time`/
`end_time` are plain `Integer` minutes-since-midnight (0-1439) rather
than a `TIME` column -- fully equivalent expressiveness for a local
wall-clock time, no new `infra.db` export needed (this product never
modifies `saas-os`).

**Tenancy**: the client tenant, same as CRM/Conversations/Marketing --
see `product/appointments/__init__.py`'s own module docstring for the
full reasoning.

**Instant vs. local time, explicitly distinguished (docs/ROADMAP.md
Phase 7's own "explicitly distinguish instant in time vs. business/local
timezone" requirement)**:
- `AvailabilityRule.start_time`/`end_time` are **local wall-clock time in
  the calendar's own `Calendar.timezone`**, not a fixed UTC instant --
  "9am-5pm every Monday" means local 9am-5pm regardless of DST shifts.
  Converting a rule to a real UTC instant for a specific calendar date
  (handling DST correctly) is `product/appointments/availability.py
  ::compute_available_slots()`'s job, not this model's.
- `Appointment.starts_at`/`ends_at` are **the canonical UTC instant**
  (`DateTime(timezone=True)`) -- a booked appointment is an actual,
  unambiguous point in time, never a local/naive timestamp.

**Composite-FK discipline**, mirroring `product/crm/models.py`/
`product/marketing/models.py` exactly: every cross-table reference here
is a `ForeignKeyConstraint` against the target table's own
`UniqueConstraint(tenant_id, id)`, never a bare `ForeignKey` on the id
column alone -- structurally impossible for a row here to reference
another tenant's calendar/contact.

**Deletion behavior** (deliberate, documented, mirrors
`conversations.threads.contact_id`'s/`marketing.campaign_recipients
.contact_id`'s own correct shape -- specifically NOT `crm.contacts
.company_id`'s original, buggy shape):
- `availability_rules.calendar_id` is `ON DELETE CASCADE` -- a rule has
  no meaning without its calendar, the same reasoning `crm.tasks`/
  `crm.notes` already established for their own parent entities.
- `appointments.contact_id` is **column-scoped** `ON DELETE SET NULL
  (contact_id)` -- deleting a contact must not destroy booking history,
  only unlink it. This is the exact fix for the defect class the
  deferred Phase 4 CRM bug demonstrated (bare `SET NULL` on a
  multi-column FK nulls every column in the FK, including the `NOT NULL`
  `tenant_id`, causing a `NotNullViolation` instead of unlinking).
- `appointments.calendar_id` has no `ON DELETE` behavior decided (the
  default `RESTRICT`) -- this phase ships no calendar-delete endpoint at
  all that could exercise it against a calendar with existing
  appointments (`product/appointments/calendars.py::delete_calendar()`
  does not check for existing appointments; a real `RESTRICT` failure
  there today surfaces as a raw `IntegrityError`, which is a genuine,
  disclosed open question for whoever revisits calendar deletion,
  mirroring exactly how `crm.pipelines`' own undecided delete semantics
  were flagged in Phase 4 -- not silently resolved here).

**The double-booking prevention constraint -- the load-bearing piece of
this entire phase, declared entirely in the migration
(`0026_create_appointments_appointments_table`), never in this ORM
model**: a PostgreSQL `EXCLUDE USING gist (calendar_id WITH =, time_range
WITH &&) WHERE (status = 'confirmed')` constraint, backed by a
`GENERATED ALWAYS AS (tstzrange(starts_at, ends_at, '[)')) STORED`
column (`btree_gist` extension, for GiST equality support on the `uuid`
`calendar_id` column). The generated `time_range` column is deliberately
**not mapped on the `Appointment` class below** -- SQLAlchemy must never
attempt to INSERT/UPDATE a value into a `GENERATED ALWAYS` column
(Postgres rejects any explicit value for one); the database computes and
maintains it, and no application code ever needs to read it directly
(every query that matters -- overlap detection, availability
computation -- goes through `starts_at`/`ends_at` and ordinary tenant-
scoped queries, per `product/appointments/availability.py`'s own module
docstring). The `[)` range (inclusive start, exclusive end) is what
correctly allows two back-to-back appointments (10:00-10:30,
10:30-11:00) on the same calendar -- they do not overlap. The `WHERE
(status = 'confirmed')` predicate is what lets a cancelled appointment's
former slot be rebooked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    Base,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
VALID_APPOINTMENT_STATUSES = (STATUS_CONFIRMED, STATUS_CANCELLED)

MINUTES_PER_DAY = 24 * 60  # 1440 -- the exclusive upper bound for start_time/end_time.

MAX_CALENDAR_NAME_LENGTH = 255
MAX_CALENDAR_EVENT_TITLE_LENGTH = 255
MAX_CALENDAR_EVENT_DESCRIPTION_LENGTH = 2000


class Calendar(Base):
    __tablename__ = "calendars"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_appointments_calendars_tenant_id_id"),
        Index("ix_appointments_calendars_tenant_id", "tenant_id"),
        {"schema": "appointments"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_CALENDAR_NAME_LENGTH), nullable=False)
    # Plain FK into the global core.users registry -- not composite,
    # mirroring how tenant_id itself references core.tenants.id (see
    # module docstring). Validated as a real TenantMembership in
    # tenant_id at the service layer (product/appointments/calendars.py),
    # not by this FK alone -- core.users has no notion of tenant
    # membership for a composite FK to express.
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id"), nullable=False)
    # IANA timezone identifier (e.g. "Europe/Amsterdam"), validated via
    # zoneinfo.ZoneInfo at the service layer before insert/update.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_appointments_availability_rules_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_availability_rules_tenant_calendar",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_appointments_availability_rules_day_of_week",
        ),
        CheckConstraint(
            "start_time >= 0 AND start_time < 1440",
            name="ck_appointments_availability_rules_start_time_bounds",
        ),
        CheckConstraint(
            "end_time > 0 AND end_time <= 1440",
            name="ck_appointments_availability_rules_end_time_bounds",
        ),
        CheckConstraint(
            "end_time > start_time",
            name="ck_appointments_availability_rules_end_after_start",
        ),
        Index("ix_appointments_availability_rules_tenant_id", "tenant_id"),
        Index("ix_appointments_availability_rules_calendar_id", "calendar_id"),
        {"schema": "appointments"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # Local wall-clock minutes-since-midnight (0-1439 start, up to 1440
    # end), in the owning calendar's own timezone -- see module
    # docstring's "instant vs. local time" section. end_time == 1440
    # (i.e. midnight, exclusive) is a deliberately allowed edge case for
    # a rule that runs to the end of the local day.
    start_time: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_appointments_appointments_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_appointments_tenant_calendar",
            # No ON DELETE behavior decided (default RESTRICT) -- see
            # module docstring; this phase ships no calendar-delete path
            # that would exercise it against a calendar with existing
            # appointments.
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_appointments_appointments_tenant_contact",
            # Column-scoped SET NULL -- see module docstring. The fix for
            # the defect class the deferred Phase 4 CRM bug demonstrated.
            ondelete="SET NULL (contact_id)",
        ),
        CheckConstraint(
            "ends_at > starts_at", name="ck_appointments_appointments_ends_after_starts"
        ),
        Index("ix_appointments_appointments_tenant_id", "tenant_id"),
        Index("ix_appointments_appointments_calendar_id", "calendar_id"),
        Index("ix_appointments_appointments_contact_id", "contact_id"),
        {"schema": "appointments"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_CONFIRMED)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )
    # NULL = no reminder sent yet; non-NULL = the UTC instant
    # product/appointments/reminders.py::send_due_reminders() sent it,
    # written only after the outbound email actually succeeds. Added by
    # migration 0029.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Deliberately NOT mapped here: the generated `time_range` column and
    # the EXCLUDE constraint that references it -- see module docstring.


class CalendarEvent(Base):
    """The generic scheduling representation (Calendar Foundation,
    docs/ROADMAP.md Phase 7.5) -- deliberately NOT a replacement for, or a
    generalization of, `Appointment` above. A row here is either:

    - a **generic event** (`appointment_id IS NULL`, `title` required) --
      an internal/personal block with no customer/business context, or
    - an **appointment-backed event** (`appointment_id` set) -- the
      calendar-grid representation of a real `Appointment`; its `title`
      may be left `NULL`, since the appointment (and the contact it
      references) is the actual source of truth for what to display, not
      a second, independently-editable copy of that text.

    The "title required unless appointment-backed" rule is enforced at
    the service layer (`product/appointments/calendar_events.py
    ::_validate_title()`) only, deliberately **not** a DB `CHECK`
    constraint -- the same shape `Appointment.status`'s own validity
    already takes (this module's own docstring on `VALID_APPOINTMENT
    _STATUSES`), and for a second, concrete reason specific to this
    table: `appointment_id` is `ON DELETE SET NULL`, so a `CHECK`
    requiring `title IS NOT NULL OR appointment_id IS NOT NULL` would
    make that `SET NULL` itself fail (`CheckViolation`) for any
    appointment-backed row left with no `title` -- silently turning a
    routine unlink into a blocked delete. No code path exercises that
    today (`Appointment` rows are never hard-deleted outside
    `product/appointments/purge.py`, and purge deletes `CalendarEvent`
    rows first -- see `product/appointments/purge.py`'s own module
    docstring), but a service-layer-only rule leaves it merely a display
    edge case (an unlinked event with no title) rather than a future
    integrity-constraint deadlock.

    This table has no bearing on `Appointment`'s own lifecycle,
    automation triggers, or reputation integration -- those all remain
    keyed on `Appointment` alone (see `product/appointments/booking.py`/
    `product/reputation/event_handlers.py`). Nothing here publishes an
    event or fires automation; `CalendarEvent` rows are purely a read/
    write scheduling projection.

    `appointment_id` is column-scoped `ON DELETE SET NULL
    (appointment_id)`, the identical shape `Appointment.contact_id`
    already uses and for the same reason: losing the appointment must not
    destroy the calendar event, only unlink it. `calendar_id` carries no
    `ON DELETE` behavior decided (default `RESTRICT`), mirroring
    `Appointment.calendar_id`'s own disclosed, undecided shape exactly --
    see this module's own docstring, "Deletion behavior"."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_appointments_calendar_events_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_calendar_events_tenant_calendar",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.appointments.tenant_id", "appointments.appointments.id"],
            name="fk_appointments_calendar_events_tenant_appointment",
            ondelete="SET NULL (appointment_id)",
        ),
        CheckConstraint(
            "ends_at > starts_at", name="ck_appointments_calendar_events_ends_after_starts"
        ),
        Index("ix_appointments_calendar_events_tenant_id", "tenant_id"),
        Index("ix_appointments_calendar_events_calendar_id", "calendar_id"),
        Index("ix_appointments_calendar_events_appointment_id", "appointment_id"),
        {"schema": "appointments"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str | None] = mapped_column(
        String(MAX_CALENDAR_EVENT_TITLE_LENGTH), nullable=True
    )
    description: Mapped[str | None] = mapped_column(
        String(MAX_CALENDAR_EVENT_DESCRIPTION_LENGTH), nullable=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class BookingLink(Base):
    """Deliberately NOT RLS-scoped, mirroring `marketing.forms`/
    `marketing.recipient_tracking_tokens`/`white_label.tenant_domains`
    exactly (see migration `0027_create_appointments_booking_links_table`'s
    own docstring): the public booking endpoint must resolve `link_token`
    -> `(tenant_id, calendar_id)` *before* any tenant context exists, so
    this table cannot live behind the ordinary RLS policy every other
    `appointments.*` table carries. Putting `link_token` directly on the
    RLS-protected `calendars` table (the first design considered) would
    make it unresolvable by an untenanted lookup -- RLS would simply
    return zero rows -- exactly the mistake this separate-table pattern
    avoids, already proven correct by `marketing.forms`/`marketing
    .recipient_tracking_tokens`.

    ONE link per calendar (1:1) -- `calendar_id` carries its own
    `UniqueConstraint`, not just `link_token`'s. See
    `product/appointments/booking.py`'s own module docstring for the
    scope-simplification reasoning (a multi-calendar "book with any
    available staff" selector is a disclosed, deferred extension, not
    silently narrowed).
    """

    __tablename__ = "booking_links"
    __table_args__ = (
        UniqueConstraint("link_token", name="uq_appointments_booking_links_link_token"),
        UniqueConstraint(
            "tenant_id", "calendar_id", name="uq_appointments_booking_links_tenant_calendar"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["appointments.calendars.tenant_id", "appointments.calendars.id"],
            name="fk_appointments_booking_links_tenant_calendar",
            ondelete="CASCADE",
        ),
        Index("ix_appointments_booking_links_tenant_id", "tenant_id"),
        Index("ix_appointments_booking_links_calendar_id", "calendar_id"),
        {"schema": "appointments"},
    )

    link_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class AppointmentManageToken(Base):
    """Deliberately NOT RLS-scoped, mirroring `BookingLink` above exactly
    and for the identical reason: `product/appointments/booking.py`'s
    public reschedule/cancel endpoints must resolve `manage_token` ->
    `(tenant_id, appointment_id)` before any tenant context exists.
    Putting this token directly on the RLS-protected `appointments`
    table (as originally drafted) would make it unresolvable by an
    untenanted lookup for the identical reason `BookingLink` is not a
    column on `calendars` -- caught and corrected during this same
    implementation pass, before it ever reached the database."""

    __tablename__ = "appointment_manage_tokens"
    __table_args__ = (
        UniqueConstraint("manage_token", name="uq_appointments_manage_tokens_manage_token"),
        UniqueConstraint(
            "tenant_id", "appointment_id", name="uq_appointments_manage_tokens_tenant_appointment"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.appointments.tenant_id", "appointments.appointments.id"],
            name="fk_appointments_manage_tokens_tenant_appointment",
            ondelete="CASCADE",
        ),
        Index("ix_appointments_manage_tokens_tenant_id", "tenant_id"),
        Index("ix_appointments_manage_tokens_appointment_id", "appointment_id"),
        {"schema": "appointments"},
    )

    manage_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    appointment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
