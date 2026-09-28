"""Shared teardown helpers for tests/accounting/*_integration.py. Extends
tests/agency/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `accounting.*` cleanup first --
`product.accounting` needs no `product.crm` dependency this phase
(`pyproject.toml`'s own "Accounting does not depend on any product module
(Phase 24)" contract), so this extends `tests/agency/_cleanup.py`
directly, mirroring `tests/billing/_cleanup.py`'s own identical "no CRM
dependency" precedent -- including its own `core.idempotency_records`
cleanup, since `post_journal_entry()`/`reverse_journal_entry()` are this
test suite's own first callers of `core.idempotency.run_idempotent()`
against a real tenant in this package.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from product.accounting import event_handlers as _accounting_event_handlers  # noqa: F401
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_ACCOUNTING_TABLES_LEAF_TO_ROOT = (
    "journal_lines",
    "journal_entries",
    "periods",
    "accounts",
)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """All four `accounting.*` tables (RLS-scoped) are deleted first, in
    dependency order, via `tenant_session_scope()`, before
    `tests/agency/_cleanup.py::cleanup_tenant_tree()`'s own tenant/
    membership/role teardown. `core.idempotency_records` is cleaned the
    same way `tests/billing/_cleanup.py`'s own identical precedent
    explains -- its `tenant_id` foreign key would otherwise block
    `tests/agency/_cleanup.py`'s own `DELETE FROM core.tenants`."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _ACCOUNTING_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM accounting.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
