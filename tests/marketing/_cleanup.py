"""Shared teardown helpers for tests/marketing/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `marketing.*` table cleanup first, in
dependency order (campaign_recipients and suppressions before campaigns).

Underscore-prefixed filename -- not itself a test module, mirrors
tests/crm/_cleanup.py's own convention.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_MARKETING_TABLES_LEAF_TO_ROOT = (
    "campaign_recipients",
    "suppressions",
    "form_submissions",
    "campaigns",
    "templates",
)
# Deliberately NOT RLS-scoped (migrations 0020/0023) -- deleted via a
# plain, untenanted session_scope() with an explicit filter, mirroring
# product/marketing/purge.py::MarketingUnscopedDataPurgeParticipant's own
# identical pattern.
_MARKETING_UNSCOPED_TABLES_LEAF_TO_ROOT = ("recipient_tracking_tokens", "forms")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`marketing.*` tables (except `forms`/`recipient_tracking_tokens`)
    are RLS-protected (FORCE ROW LEVEL SECURITY), so deleting them
    requires `tenant_session_scope(tenant_id)` -- mirrors
    `tests/crm/_cleanup.py::cleanup_tenant_tree()`'s own identical
    reasoning."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _MARKETING_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM marketing.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
        with session_scope() as session:
            for table in _MARKETING_UNSCOPED_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM marketing.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
