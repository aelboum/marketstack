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

`core.usage_events` (SaaS-OS-owned, RLS-scoped) is this test suite's own
responsibility for the identical reason `core.idempotency_records` already
is (module comment below): `product/billing/resale_plans.py
::create_resale_plan()`'s SaaS entitlement-enforcement follow-up calls
`core.usage.consume_quota()`, which inserts one `UsageEvent` row for the
reseller tenant on every successful call -- left uncleaned, its `tenant_id`
foreign key (`core/usage/models.py::UsageEvent`, no `ON DELETE CASCADE`)
blocks `tests/agency/_cleanup.py::cleanup_tenant_tree()`'s own
`DELETE FROM core.tenants` exactly like an unclean idempotency record would.

`core.billing_accounts`/`core.billing_merchant_accounts` (B2B2C Billing
Foundation, Step 2 -- `product/billing/parties.py`) are this test suite's
responsibility for the same reason, in two passes (function docstring
below): any tenant in a `test_commercial_parties_integration.py` case may
own a merchant, a billing account at another tenant's merchant, or both.

`core.billing_provider_refs` (B2B2C Sponsored Subscriptions, Step 3 --
`core/billing/commercial.py::create_subscription()`, the first product
code path to ever write one) is this test suite's responsibility for the
identical reason `core.idempotency_records` already is: its `tenant_id`
foreign key (always the *service* tenant, never the payer -- read
directly against the frozen SHA) is NOT NULL and has no
`ON DELETE CASCADE`, so left uncleaned it blocks
`tests/agency/_cleanup.py::cleanup_tenant_tree()`'s own
`DELETE FROM core.tenants` exactly like an unclean idempotency record
would. Deliberately NOT RLS-scoped (its own model docstring, "GLOBAL-BY-
DESIGN"), but still reachable and deletable through a tenant-scoped
session, since no RLS policy restricts it.

`core.outbox_events`/`core.outbox_consumptions` (SaaS-OS-owned, RLS-scoped
Reliability & Events substrate) are, for the identical reason, this test
suite's responsibility starting with Step 3 -- `core.billing.commercial
.create_subscription()`'s own `_insert_pending()` appends one payer/seller-
projection `OutboxEvent` in the same transaction as the subscription row
(confirmed directly against the frozen SHA); no earlier product code path
ever wrote one against a real tenant, so no existing `tests/*/_cleanup.py`
knows about either table, and both carry a NOT NULL `tenant_id` foreign
key with no `ON DELETE CASCADE`.

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
            # B2B2C Billing Foundation, Step 2 (product/billing/parties.py):
            # core.billing_accounts (payer-owned) is deleted before
            # core.billing_merchant_accounts (payee-owned) to respect
            # fk_billing_accounts_merchant_account's own direction -- a
            # billing account can reference a merchant owned by a
            # *different* tenant than its own payer, so this must run as
            # its own pass per tenant_id before any of this call's other
            # tenant_ids' merchant rows are removed.
            session.execute(
                text("DELETE FROM core.billing_accounts WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.billing_provider_refs WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.usage_events WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.outbox_consumptions WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text("DELETE FROM core.outbox_events WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    # Second pass, after every tenant_id's own core.billing_accounts rows
    # are gone: a billing account owned by one of these tenants may have
    # referenced a merchant owned by *another* of these tenants (e.g. a
    # test tenant's own self-pay billing account at the platform
    # merchant), so no core.billing_merchant_accounts row in this batch
    # can be deleted until every billing account in the batch is gone.
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM core.billing_merchant_accounts WHERE tenant_id = :t"),
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
