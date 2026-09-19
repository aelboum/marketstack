"""Shared teardown helpers for tests/crm/*_integration.py. Extends
tests/agency/_cleanup.py's own proven `cleanup_tenant_tree()`/
`cleanup_users()`/`make_user()` (reused directly, not re-derived) with
`crm.*` table cleanup first, in dependency order (tasks/notes, then
opportunities, then contacts/pipeline_stages, then companies/pipelines)
-- `ON DELETE CASCADE`/`SET NULL` on the individual FKs
(product/crm/models.py) would handle most of this automatically once the
referenced row is deleted, but deleting explicitly, in order, here is
what actually proves the ordering is safe rather than relying on it.

Underscore-prefixed filename -- not itself a test module, mirrors
tests/agency/_cleanup.py's own convention.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_CRM_TABLES_LEAF_TO_ROOT = (
    "tasks",
    "notes",
    "custom_field_values",
    "entity_tags",
    "import_jobs",
    "opportunities",
    "contacts",
    "pipeline_stages",
    "companies",
    "pipelines",
    "custom_field_definitions",
    "tags",
)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`crm.*` tables are RLS-protected (FORCE ROW LEVEL SECURITY), so
    deleting them requires `tenant_session_scope(tenant_id)` -- a plain
    `session_scope()` running as the restricted app role would silently
    affect zero rows (RLS, not an error), never actually cleaning up."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _CRM_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM crm.{table} WHERE tenant_id = :t"), {"t": str(tenant_id)}
                )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
