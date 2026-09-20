"""ORM models for the `telephony` schema (docs/ROADMAP.md Phase 8.1-8.3).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like `product/appointments/models.py` -- this module
never imports `sqlalchemy` directly.

**`PhoneNumber` is deliberately NOT RLS-scoped** -- mirrors
`product/appointments/models.py::BookingLink`/`product/white_label/models.py
::TenantDomain`'s identical precedent and reasoning: an inbound provider
webhook's `to_number` is the only signal available to resolve which
tenant it belongs to, and that resolution must happen *before* any tenant
context exists (`product/telephony/calls.py::receive_inbound_call_event()`
never trusts a tenant id supplied by the event payload itself). Putting
`phone_number` on an RLS-protected table would make it unresolvable by
that untenanted lookup -- RLS would simply return zero rows, the exact
mistake `BookingLink`/`TenantDomain` already avoid. `PhoneNumber` still
carries `UniqueConstraint(tenant_id, id)` (needed for composite FKs from
`Call`/`PhoneNumberRoutingTarget`) even without RLS -- RLS is a Postgres
policy layered on top of a table, structurally independent of whether a
composite-FK target unique index exists.

Every other table here (`PhoneNumberRoutingTarget`, `Call`, `CallEvent`,
`CallRecording`) is ordinary RLS-scoped, tenant-owned data, reached only
after `PhoneNumber` lookup has already established `tenant_id` -- exactly
`product/appointments/models.py::Calendar`/`Appointment`'s own relationship
to `BookingLink`.

**Composite-FK discipline**, mirroring every other product module's models
exactly: every cross-table reference here is a `ForeignKeyConstraint`
against the target table's own `UniqueConstraint(tenant_id, id)`, never a
bare `ForeignKey` on the id column alone.

**Deletion behavior** (deliberate, documented, applying the fix for the
defect class the deferred Phase 4 CRM bug demonstrated):
- `phone_number_routing_targets.phone_number_id` is `ON DELETE CASCADE`
  -- a routing target has no meaning without its phone number.
- `calls.contact_id` is **column-scoped** `ON DELETE SET NULL (contact_id)`
  -- deleting a contact must not destroy call history, only unlink it.
  The identical fix `product/appointments/models.py::Appointment.contact_id`
  already applies, for the identical reason.
- `calls.phone_number_id` has no `ON DELETE` behavior decided (the default
  `RESTRICT`) -- this phase ships no phone-number-release endpoint that
  checks for existing calls first; a real `RESTRICT` failure there today
  surfaces as a raw `IntegrityError`, a genuine, disclosed open question,
  mirroring exactly how `appointments.calendar_id`'s own undecided delete
  semantics were flagged in Phase 7.
- `call_events.call_id`/`call_recordings.call_id` are `ON DELETE CASCADE`
  -- neither has meaning without its parent call.

**The call state machine** -- see `product/telephony/calls.py`'s own
module docstring for the full, explicit transition table this phase
enforces at the service layer (never a bare, unconstrained `status`
column write). `VALID_CALL_STATUSES`/`TERMINAL_CALL_STATUSES` below are
this model's own declared vocabulary; the transition table itself lives
in `calls.py`, not here, mirroring how `appointments.models`'s own
`EXCLUDE` constraint mechanics live in its migration, not its ORM class.

**Idempotency/replay protection is a database-enforced invariant, not an
application-level check-then-insert**: `CallEvent`'s
`UniqueConstraint(tenant_id, provider_name, provider_event_id)` is what
actually makes double-processing of the same provider event impossible --
`product/telephony/calls.py::receive_inbound_call_event()` performs the
insert and translates the resulting `IntegrityError` into a no-op, never a
"check then insert" as its own guarantee (mirrors
`product/appointments/models.py`'s own module docstring on the `EXCLUDE`
constraint / `booking.py`'s identical discipline).
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

STATUS_NUMBER_ACTIVE = "active"
STATUS_NUMBER_RELEASED = "released"
VALID_PHONE_NUMBER_STATUSES = (STATUS_NUMBER_ACTIVE, STATUS_NUMBER_RELEASED)

DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"
VALID_CALL_DIRECTIONS = (DIRECTION_INBOUND, DIRECTION_OUTBOUND)

STATUS_RINGING = "ringing"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_NO_ANSWER = "no_answer"
STATUS_FAILED = "failed"
VALID_CALL_STATUSES = (
    STATUS_RINGING,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_NO_ANSWER,
    STATUS_FAILED,
)
TERMINAL_CALL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_NO_ANSWER, STATUS_FAILED})

MAX_PHONE_NUMBER_LENGTH = 32
MAX_PROVIDER_NAME_LENGTH = 64
MAX_PROVIDER_ID_LENGTH = 255


class PhoneNumber(Base):
    """NOT RLS-scoped -- see module docstring."""

    __tablename__ = "phone_numbers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_telephony_phone_numbers_tenant_id_id"),
        UniqueConstraint("phone_number", name="uq_telephony_phone_numbers_phone_number"),
        Index("ix_telephony_phone_numbers_tenant_id", "tenant_id"),
        {"schema": "telephony"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(MAX_PHONE_NUMBER_LENGTH), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(MAX_PROVIDER_NAME_LENGTH), nullable=False)
    provider_number_id: Mapped[str] = mapped_column(String(MAX_PROVIDER_ID_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_NUMBER_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class PhoneNumberRoutingTarget(Base):
    __tablename__ = "phone_number_routing_targets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_telephony_routing_targets_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "phone_number_id",
            "position",
            name="uq_telephony_routing_targets_tenant_number_position",
        ),
        UniqueConstraint(
            "tenant_id",
            "phone_number_id",
            "user_id",
            name="uq_telephony_routing_targets_tenant_number_user",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "phone_number_id"],
            ["telephony.phone_numbers.tenant_id", "telephony.phone_numbers.id"],
            name="fk_telephony_routing_targets_tenant_phone_number",
            ondelete="CASCADE",
        ),
        Index("ix_telephony_routing_targets_tenant_id", "tenant_id"),
        Index("ix_telephony_routing_targets_phone_number_id", "phone_number_id"),
        {"schema": "telephony"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    phone_number_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Plain FK into the global core.users registry -- not composite,
    # mirroring Calendar.owner_user_id exactly. Validated as a real
    # TenantMembership/SUBTREE reach at the service layer
    # (product/telephony/numbers.py), via core.rbac.can(), not by this FK
    # alone.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_telephony_calls_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "phone_number_id"],
            ["telephony.phone_numbers.tenant_id", "telephony.phone_numbers.id"],
            name="fk_telephony_calls_tenant_phone_number",
            # No ON DELETE behavior decided (default RESTRICT) -- see
            # module docstring.
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_telephony_calls_tenant_contact",
            # Column-scoped SET NULL -- see module docstring. Same fix as
            # product/appointments/models.py::Appointment.contact_id.
            ondelete="SET NULL (contact_id)",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound')", name="ck_telephony_calls_direction"
        ),
        CheckConstraint(
            "status IN ('ringing', 'in_progress', 'completed', 'no_answer', 'failed')",
            name="ck_telephony_calls_status",
        ),
        Index("ix_telephony_calls_tenant_id", "tenant_id"),
        Index("ix_telephony_calls_phone_number_id", "phone_number_id"),
        Index("ix_telephony_calls_contact_id", "contact_id"),
        Index("ix_telephony_calls_assigned_user_id", "assigned_user_id"),
        # Partial unique index -- provider_call_id is only known once a
        # provider has actually assigned one (never for a call still being
        # placed), so NULLs (many) must not collide under uniqueness.
        Index(
            "uq_telephony_calls_tenant_provider_call",
            "tenant_id",
            "provider_name",
            "provider_call_id",
            unique=True,
            postgresql_where="provider_call_id IS NOT NULL",
        ),
        {"schema": "telephony"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    phone_number_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider_name: Mapped[str] = mapped_column(String(MAX_PROVIDER_NAME_LENGTH), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(
        String(MAX_PROVIDER_ID_LENGTH), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    from_number: Mapped[str] = mapped_column(String(MAX_PHONE_NUMBER_LENGTH), nullable=False)
    to_number: Mapped[str] = mapped_column(String(MAX_PHONE_NUMBER_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_RINGING)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class CallEvent(Base):
    """The idempotency/replay-protection ledger -- see module docstring.
    Deliberately carries no raw provider payload column: `event_type` +
    the identifiers here are enough to dedupe and to know what happened;
    an arbitrary provider payload is exactly the kind of unbounded,
    potentially-PII-carrying blob this phase's own audit/PII discipline
    says not to persist without a proven need."""

    __tablename__ = "call_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_telephony_call_events_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "provider_name",
            "provider_event_id",
            name="uq_telephony_call_events_tenant_provider_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["telephony.calls.tenant_id", "telephony.calls.id"],
            name="fk_telephony_call_events_tenant_call",
            ondelete="CASCADE",
        ),
        Index("ix_telephony_call_events_tenant_id", "tenant_id"),
        Index("ix_telephony_call_events_call_id", "call_id"),
        {"schema": "telephony"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider_name: Mapped[str] = mapped_column(String(MAX_PROVIDER_NAME_LENGTH), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(MAX_PROVIDER_ID_LENGTH), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class CallRecording(Base):
    """Service-layer-only (`product/telephony/recordings.py`) -- no route
    exposes this table at all, see `product/telephony/__init__.py`'s own
    module docstring on Phase 8.3's "dedicated security review" gate."""

    __tablename__ = "call_recordings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_telephony_call_recordings_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["telephony.calls.tenant_id", "telephony.calls.id"],
            name="fk_telephony_call_recordings_tenant_call",
            ondelete="CASCADE",
        ),
        Index("ix_telephony_call_recordings_tenant_id", "tenant_id"),
        Index("ix_telephony_call_recordings_call_id", "call_id"),
        {"schema": "telephony"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
