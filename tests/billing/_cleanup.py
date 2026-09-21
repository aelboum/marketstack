"""Shared teardown helpers for tests/billing/*_integration.py. Extends
tests/agency/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `billing.resale_plans`/
`core.billing_subscriptions` cleanup first -- `product.billing` needs no
`product.crm` dependency (docs/ADR/0012-...), so this extends
`tests/agency/_cleanup.py` directly, mirroring `tests/websites/_cleanup.py`'s
own identical "no CRM dependency" precedent.

`cleanup_global_plan_keys()` additionally removes this test suite's own
`core.billing_plans` rows (GLOBAL, not tenant-scoped -- `core.billing`
exposes no `delete_plan()`, so this reaches the table directly via an
admin session, exactly `tests/agency/_cleanup.py::_admin_session()`'s own
migrations-role connection) -- test hygiene only, keeping the shared
development database's global catalog from accumulating stale rows across
repeated runs; never required for test *correctness* (each test's own
`key`/`underlying_plan_key` is always freshly generated).

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import (
    build_engine,
    build_session_factory,
    get_migrations_database_config,
    session_scope,
    tenant_session_scope,
)
from product.billing import event_handlers as _billing_event_handlers  # noqa: F401
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_global_plan_keys", "cleanup_tenant_tree", "cleanup_users", "make_user"]


def _admin_session():
    engine = build_engine(get_migrations_database_config())
    factory = build_session_factory(engine)
    return session_scope(session_factory=factory)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`billing.resale_plans` (RLS-scoped) and `core.billing_subscriptions`
    (RLS-scoped, SaaS-OS-owned) are deleted first, via `tenant_session_scope()`,
    before `tests/agency/_cleanup.py::cleanup_tenant_tree()`'s own
    tenant/membership/role teardown. `core.idempotency_records` is this
    test suite's own responsibility too -- `core.billing.subscribe_idempotent()`
    (`product/billing/subscriptions.py`) is the first product code path to
    ever write one against a real tenant, so `tests/agency/_cleanup.py`'s
    own table list predates it and does not know about it; left uncleaned,
    its `tenant_id` foreign key blocks `tests/agency/_cleanup.py`'s own
    `DELETE FROM core.tenants`."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM billing.resale_plans WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.billing_subscriptions WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)


def cleanup_global_plan_keys(*keys: str) -> None:
    if not keys:
        return
    with _admin_session() as session:
        session.execute(
            text("DELETE FROM core.billing_plans WHERE key = ANY(:keys)"), {"keys": list(keys)}
        )
