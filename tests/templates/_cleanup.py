"""Shared teardown helpers for tests/templates/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `templates.snapshots` table cleanup first
-- mirrors tests/appointments/_cleanup.py's own extension pattern for the
identical reason (`product/templates`'s own `docs/ADR/0013-...` CRM
dependency).

Imports both `product.crm.event_handlers` and `product.templates
.event_handlers` solely for their module-level `subscribe("agency
.role_provisioned", ...)` side effects -- this package has no HTTP-level
test of its own to trigger `product/api/main.py`'s transitive imports the
way `tests/appointments/test_booking_integration.py` does for its own
package (`product/templates/__init__.py`'s own module docstring: the
`product/api/main.py` wiring is deferred in this phase), so both
subscriptions are registered explicitly here instead.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from product.crm import event_handlers as _crm_event_handlers  # noqa: F401
from product.templates import event_handlers as _templates_event_handlers  # noqa: F401
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`templates.snapshots` is RLS-scoped -- deleted first, via
    `tenant_session_scope()`. `crm.*` cleanup (which snapshot payloads
    reference by NAME only, never by id -- `docs/ADR/0013-...`'s own
    "Decision 2") happens afterward, via the wrapped `tests/crm/_cleanup.py
    ::cleanup_tenant_tree()` call."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM templates.snapshots WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
