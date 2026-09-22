"""Shared teardown helpers for tests/websites/*_integration.py.

**Now extends `tests/crm/_cleanup.py`, not `tests/agency/_cleanup.py`
directly** -- docs/ROADMAP.md Phase 22 gave `product.websites` its own,
narrow `product.crm` edge (`docs/ADR/0015-websites-depends-on-crm.md`),
via `product/websites/leads.py::capture_lead()`'s real
`crm.contacts` write. This mirrors `tests/marketing/_cleanup.py`'s/
`tests/appointments/_cleanup.py`'s own identical extension, for the
identical reason: these tests can now create real `crm.contacts` rows
too, so `websites.*` cleanup must run before CRM cleanup, which itself
runs before the tenant/agency cleanup underneath it.

Also purges `core.idempotency_records` -- `capture_lead()` reuses
`core.idempotency.run_idempotent()` (module docstring of
`product/websites/leads.py`), which persists a row FK'd to
`core.tenants`; a test tenant with any recorded reservation cannot
otherwise be deleted at all. Mirrors `tests/automation/_cleanup.py`'s own
identical, independently-added fix for the same table (that module's own
`execute_step_action_activity()` reuses the same primitive).

Deletes, in order: `websites.lead_submissions` (RLS-scoped, references
both `websites.pages` and `crm.contacts`) -> `websites.pages` (RLS-scoped)
-> `websites.websites` (deliberately NOT RLS-scoped, via a plain
`session_scope()` with an explicit `tenant_id` filter, mirroring
`tests/telephony/_cleanup.py`'s own identical scoped/unscoped split) ->
`core.idempotency_records` -> (via the wrapped call) `crm.*` ->
agency/tenant rows.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`websites.lead_submissions` and `websites.pages` (both RLS-scoped)
    are deleted first, then `websites.websites` (unscoped, explicit
    `tenant_id` filter) -- mirrors `tests/telephony/_cleanup.py
    ::cleanup_tenant_tree()`'s own identical two-pass shape, extended with
    Phase 22's new table. Every FK involved is already `ON DELETE
    CASCADE`/column-scoped `SET NULL` (`product/websites/models.py`'s own
    docstrings), so the FKs would handle the ordering automatically;
    deleting explicitly, in order, here is still what actually proves it,
    not merely relies on it."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM websites.lead_submissions WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM websites.pages WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
        with session_scope() as session:
            session.execute(
                text("DELETE FROM websites.websites WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
