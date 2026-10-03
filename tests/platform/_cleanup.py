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

`core.billing_merchant_accounts`/`core.billing_accounts` (B2B2C Billing
Foundation, Step 2 -- `product/billing/parties.py`) join this file's own
table list for the identical reason: `bootstrap_platform_tenant()`
reactively provisions the platform tenant's own `MerchantAccount` on
every call (`product/billing/event_handlers.py`'s `platform
.role_provisioned` subscription) -- `tests/platform/test_*_integration.py`'s
own `platform` fixture is one of only two call shapes for that function
in the whole repository (the other, `tests/billing/
test_commercial_parties_integration.py`, uses `tests/billing/_cleanup.py`'s
own already-extended version), so this is the one other place that needs
it. Mirrors `tests/billing/_cleanup.py`'s own two-pass ordering (billing
accounts, which may reference another tenant's merchant, deleted before
any merchant account in the same batch) -- a harmless no-op here today
(no `tests/platform/` test creates a `BillingAccount`), kept for the
identical defensive reason the `idempotency_records` delete already is:
a harmless no-op for any tenant id that never created one.

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
            session.execute(
                text("DELETE FROM core.billing_accounts WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM core.billing_merchant_accounts WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
