"""Shared teardown helpers for tests/accounting/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `accounting.*` cleanup first (now including
`credit_notes`/`credit_note_lines`, docs/ROADMAP.md Phase 15.3 -- deleted
before `invoices`, since `credit_notes.invoice_id` carries a `RESTRICT` FK
to it, the identical "child before RESTRICT-referenced parent" ordering
this file's own table tuple already applies everywhere else) --
`product.accounting` now depends on `product.crm` as of Phase 25
(`pyproject.toml`'s own "Accounting may depend on CRM, never CRM on
Accounting" layers contract, ADR-0014 Decision 6), so this extends
tests/crm/_cleanup.py directly (no longer tests/agency/_cleanup.py, which
was Phase 24's own precedent before this edge existed), mirroring
tests/marketing/_cleanup.py's own identical "depends on CRM" precedent --
including its own `core.idempotency_records` cleanup, since
`post_journal_entry()`/`reverse_journal_entry()`/`post_invoice()`/
`post_bill()`/`create_allocation()` are this test suite's own callers of
`core.idempotency.run_idempotent()` against a real tenant in this package.

`accounting.contact_profiles`/`accounting.invoices`/`accounting.bills` all
carry a `RESTRICT` (never CASCADE) FK to `crm.contacts` (ADR-0014 Decision
6 addendum) -- every accounting.* table must be deleted here *before*
`tests/crm/_cleanup.py::cleanup_tenant_tree()` runs, or its own
`DELETE FROM crm.contacts` would fail with a raw `IntegrityError`.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from product.accounting import event_handlers as _accounting_event_handlers  # noqa: F401
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

# Leaf-to-root: allocations/lines before their documents/payments, then
# documents/payments before the accounts/periods/journal rows they
# reference, then contact_profiles last among accounting's own tables
# (it has no accounting-internal dependent) -- and always before
# `tests/crm/_cleanup.py`'s own `DELETE FROM crm.contacts` runs.
_ACCOUNTING_TABLES_LEAF_TO_ROOT = (
    "bank_statement_lines",
    "bank_statements",
    "bank_accounts",
    "payment_allocations",
    "payments",
    "bill_lines",
    "bills",
    "credit_note_lines",
    "credit_notes",
    "invoice_lines",
    "invoices",
    "journal_lines",
    "journal_entries",
    "tax_codes",
    "periods",
    "accounts",
    "contact_profiles",
)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """All seventeen `accounting.*` tables (RLS-scoped) are deleted first, in
    dependency order, via `tenant_session_scope()`, before
    `tests/crm/_cleanup.py::cleanup_tenant_tree()`'s own crm/tenant/
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
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
