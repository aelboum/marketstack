"""Shared teardown helpers for tests/conversations/*_integration.py.
Extends tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()`
(reused directly, not re-derived) with `conversations.*` table cleanup
first, in dependency order (messages before threads; message_templates
has no FK to anything else in this schema and can go in any position).

Underscore-prefixed filename -- not itself a test module, mirrors
tests/crm/_cleanup.py's own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_CONVERSATIONS_TABLES_LEAF_TO_ROOT = ("messages", "threads", "message_templates")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`conversations.*` tables are RLS-protected (FORCE ROW LEVEL
    SECURITY), so deleting them requires `tenant_session_scope(tenant_id)`
    -- mirrors `tests/crm/_cleanup.py::cleanup_tenant_tree()`'s own
    identical reasoning."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _CONVERSATIONS_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM conversations.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
