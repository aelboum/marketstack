"""Tenant purge participants for the `telephony` schema (mirrors
`product/appointments/purge.py`'s proven two-participant pattern).
Registered from `product/api/main.py::create_app()`.

**Two participants, not one** -- identical reason to
`product/appointments/purge.py`'s own docstring:

- `TelephonyDataPurgeParticipant` covers every ordinary, RLS-scoped
  `telephony.*` table (`call_recordings`, `call_events`, `calls`,
  `phone_number_routing_targets`) via the normal `tenant_session_scope()`
  path. Deletion order: leaves before roots, regardless of what
  `ON DELETE` behavior each individual FK happens to carry (defense in
  depth, matching `phone_number_id`'s own undecided `ON DELETE` per
  `product/telephony/models.py`'s docstring).
- `TelephonyUnscopedDataPurgeParticipant` covers `phone_numbers` --
  deliberately NOT RLS-scoped (see `product/telephony/models.py`'s own
  docstring), so this participant reads through a plain `session_scope()`
  with an explicit `tenant_id` filter instead, mirroring
  `product/appointments/purge.py::AppointmentsUnscopedDataPurgeParticipant`'s
  identical pattern.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, session_scope, tenant_session_scope

from product.telephony.models import (
    Call,
    CallEvent,
    CallRecording,
    PhoneNumber,
    PhoneNumberRoutingTarget,
)

_SCOPED_PURGE_ORDER = (
    CallRecording,
    CallEvent,
    Call,
    PhoneNumberRoutingTarget,
)

_UNSCOPED_PURGE_ORDER = (PhoneNumber,)


class TelephonyDataPurgeParticipant:
    """Deletes every ordinary, RLS-scoped `telephony.*` row belonging to
    the tenant being purged, in dependency order. Idempotent."""

    @property
    def name(self) -> str:
        return "telephony.*"

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


class TelephonyUnscopedDataPurgeParticipant:
    """Deletes every `telephony.phone_numbers` row mapped to the tenant
    being purged, via a plain, untenanted `session_scope()` with an
    explicit `tenant_id` filter -- this table carries no RLS policy to
    rely on instead (see module docstring). Idempotent."""

    @property
    def name(self) -> str:
        return "telephony.unscoped"

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
    re-registration/idempotency reasoning."""
    active_registry = registry if registry is not None else default_registry()
    for participant in (
        TelephonyDataPurgeParticipant(),
        TelephonyUnscopedDataPurgeParticipant(),
    ):
        try:
            active_registry.register(participant)
        except DuplicateTenantPurgeParticipantError:
            if not any(
                isinstance(p, type(participant)) for p in active_registry.list()
            ):  # pragma: no cover -- would mean a *different* type reused this name
                raise
