"""Shared teardown helpers for tests/reputation/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `reputation.*` table cleanup first, in
dependency order (review_responses before reviews before review_requests)
-- mirrors tests/appointments/_cleanup.py's own extension pattern for the
identical reason (`product/reputation`'s own `docs/ADR/0010-...` CRM
dependency).

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope

# Imported solely for their module-level `subscribe("agency
# .role_provisioned", ...)` side effects (`product/reputation
# /event_handlers.py`'s and `product/crm/event_handlers.py`'s own
# docstrings) -- every other module's identical import lives in
# `product/api/main.py`, and every other module's own test package works
# in isolation only because it *also* contains its own
# `test_routes_integration.py::create_app()` call, which transitively
# imports every module's `event_handlers.py` (e.g.
# `tests/appointments/test_booking_integration.py`,
# `tests/marketing/test_routes_integration.py`). This package needs the
# identical CRM grant (`create_contact()`/`get_contact()`, docs/ADR/0010
# -reputation-depends-on-crm.md) but has no HTTP-level test of its own --
# `product/api/main.py`'s own reputation wiring is deferred (see
# `product/reputation/__init__.py`'s own module docstring) -- so both
# subscriptions are imported explicitly here instead, guaranteeing they
# are registered before any test in this package runs, regardless of
# collection scope or order.
from product.crm import event_handlers as _crm_event_handlers  # noqa: F401
from product.reputation import event_handlers as _reputation_event_handlers  # noqa: F401
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_REPUTATION_TABLES_LEAF_TO_ROOT = ("review_responses", "reviews", "review_requests")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """All three `reputation.*` tables are RLS-scoped -- deleted first, in
    dependency order, via `tenant_session_scope()`. `crm.contacts` cleanup
    (which `reputation.review_requests.contact_id` references) happens
    afterward, via the wrapped `tests/crm/_cleanup.py::cleanup_tenant_tree()`
    call -- safe regardless of ordering (`ON DELETE CASCADE`), but deleting
    reputation rows first is the defense-in-depth discipline every other
    `_cleanup.py` in this test suite already follows."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _REPUTATION_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM reputation.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
