"""Shared teardown helpers for tests/automation/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` with
`automation.*` table cleanup first (workflow_runs before workflows).
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_AUTOMATION_TABLES_LEAF_TO_ROOT = ("workflow_runs", "workflows")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _AUTOMATION_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM automation.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
