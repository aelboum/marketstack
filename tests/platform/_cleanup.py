"""Shared teardown helpers for tests/platform/*_integration.py.

`product.platform` introduces zero new tables of its own (its own module
docstring: a platform tenant is an ordinary `core.tenants` row, a
`platform_owner` role an ordinary `core.roles` row) -- but
`attach_agency_to_platform()`'s own "Audit correctness" section
(`product/platform/provisioning.py`) reuses `core.idempotency
.begin_idempotent_operation()`, which persists one `core.idempotency_records`
row keyed at the *platform* tenant (`platform_tenant.id`) on every call.
`product.platform` is the first product code path to ever write one
against the platform tenant specifically; `tests/agency/_cleanup.py`'s own
table list predates it and does not know about it -- left uncleaned, its
`tenant_id` foreign key blocks that same module's own
`DELETE FROM core.tenants`, exactly like `tests/billing/_cleanup.py`'s own
identical, independently-added fix for the same table (that module's own
`subscribe_idempotent()` reuses the same primitive; `tests/automation/
_cleanup.py` and `tests/websites/_cleanup.py` each document the same fix a
third and fourth time, for their own respective first write).

No CRM dependency (mirrors `tests/websites/_cleanup.py`'s/
`tests/billing/_cleanup.py`'s own identical precedent) -- this extends
`tests/agency/_cleanup.py` directly.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """Deletes this tenant's own `core.idempotency_records` rows first, via
    `tenant_session_scope()`, before `tests/agency/_cleanup.py
    ::cleanup_tenant_tree()`'s own tenant/membership/role teardown -- a
    harmless no-op for any tenant id that never reserved one (every Agency/
    Client tenant id these tests also pass through here)."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
