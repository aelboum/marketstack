"""Shared teardown helpers for tests/telephony/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `telephony.*` table cleanup first, in
dependency order (call_recordings/call_events before calls, before
phone_number_routing_targets), mirroring tests/appointments/_cleanup.py's
exact scoped/unscoped split for the identical reason
(`telephony.phone_numbers` is deliberately NOT RLS-scoped, see
product/telephony/models.py's own docstring).

Underscore-prefixed filename -- not itself a test module, mirrors
tests/appointments/_cleanup.py's own convention.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_TELEPHONY_TABLES_LEAF_TO_ROOT = (
    "call_recordings",
    "call_events",
    "calls",
    "phone_number_routing_targets",
)
_TELEPHONY_UNSCOPED_TABLES_LEAF_TO_ROOT = ("phone_numbers",)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`telephony.*` RLS-scoped tables are deleted first, then
    `phone_numbers` via a plain, untenanted `session_scope()` with an
    explicit `tenant_id` filter -- mirrors
    `tests/appointments/_cleanup.py::cleanup_tenant_tree()`'s own
    identical two-pass shape. `crm.contacts` cleanup (which
    `telephony.calls.contact_id` references) happens afterward, via the
    wrapped `tests/crm/_cleanup.py::cleanup_tenant_tree()` call -- safe
    regardless of ordering (`ON DELETE SET NULL (contact_id)`)."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _TELEPHONY_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM telephony.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
        with session_scope() as session:
            for table in _TELEPHONY_UNSCOPED_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM telephony.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
