"""Shared teardown helpers for tests/appointments/*_integration.py.
Extends tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()`
(reused directly, not re-derived) with `appointments.*` table cleanup
first, in dependency order (calendar_events/appointments/availability_rules
before calendars), mirroring tests/marketing/_cleanup.py's exact scoped/
unscoped split for the identical reason (`appointments.booking_links`/
`appointments.appointment_manage_tokens` are deliberately NOT
RLS-scoped, see product/appointments/models.py's own docstrings).

Underscore-prefixed filename -- not itself a test module, mirrors
tests/marketing/_cleanup.py's own convention.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_APPOINTMENTS_TABLES_LEAF_TO_ROOT = (
    "calendar_events",
    "appointments",
    "availability_rules",
    "calendars",
)
_APPOINTMENTS_UNSCOPED_TABLES_LEAF_TO_ROOT = ("appointment_manage_tokens", "booking_links")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`appointments.*` RLS-scoped tables are deleted first (leaf-to-root:
    `calendar_events` before `appointments` before `availability_rules`
    before `calendars`), then
    the two unscoped token tables via a plain, untenanted `session_scope()`
    with an explicit `tenant_id` filter -- mirrors
    `tests/marketing/_cleanup.py::cleanup_tenant_tree()`'s own identical
    two-pass shape. `crm.contacts` cleanup (which `appointments.appointments
    .contact_id` references) happens afterward, via the wrapped
    `tests/crm/_cleanup.py::cleanup_tenant_tree()` call -- this is safe
    regardless of ordering (`ON DELETE SET NULL (contact_id)`), but
    deleting appointments first is the defense-in-depth discipline every
    other `_cleanup.py` in this test suite already follows."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _APPOINTMENTS_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM appointments.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
        with session_scope() as session:
            for table in _APPOINTMENTS_UNSCOPED_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM appointments.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
