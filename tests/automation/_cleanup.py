"""Shared teardown helpers for tests/automation/*_integration.py. Extends
tests/crm/_cleanup.py's own proven `cleanup_tenant_tree()` with
`automation.*` table cleanup first (10.2's own `workflow_runs` before
`workflows`; docs/ROADMAP.md Phase 10.3's own `durable_run_steps` ->
`durable_runs` -> `durable_workflow_versions` -> `durable_workflows`,
leaf to root, identical ordering discipline), and, since Phase 10.3's
own `business_activities.py::execute_step_action_activity()` reuses
`core.idempotency` (`docs/ADR/0007-automation-execution-substrate.md`'s
own Phase 10.3 section), purges this tenant's own
`core.idempotency_records` rows too -- `core.tenants` carries a
`FOREIGN KEY` from that table, so a test tenant with any recorded
idempotency reservation cannot otherwise be deleted at all.
`core.idempotency.service.purge_tenant_idempotency_records()` does
exactly this, but is not part of that package's own curated public
`__init__.py` export list -- this test-only helper reaches directly into
`core.idempotency_records` via `DELETE` instead, the same way every
other `tests/*/_cleanup.py` in this codebase already reaches into a
`core`-owned table it has no public purge function for (a test-cleanup-
only convention; production code never does this).
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_AUTOMATION_TABLES_LEAF_TO_ROOT = (
    "workflow_runs",
    "workflows",
    "durable_run_steps",
    "durable_runs",
    "durable_workflow_versions",
    "durable_workflows",
)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            for table in _AUTOMATION_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM automation.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            session.execute(
                text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
