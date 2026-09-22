"""Shared teardown helpers for tests/approvals/*_integration.py.
`product/approvals/` owns no table of its own (module docstring) -- the
only extra row type these tests create beyond the ordinary agency/user
tree is `control_plane.approval_requests`, created directly via
`control_plane.approvals.propose_action()` (never through product code,
matching this phase's own scope: creation is not a Phase 29 concern).

Underscore-prefixed filename -- not itself a test module, mirrors every
other `_cleanup.py` in this test suite.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM control_plane.approval_requests WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
