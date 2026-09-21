"""Shared teardown helpers for tests/websites/*_integration.py. Extends
tests/agency/_cleanup.py's own proven `cleanup_tenant_tree()` (reused
directly, not re-derived) with `websites.*` table cleanup first --
`websites.pages` (RLS-scoped, via `tenant_session_scope()`) before
`websites.websites` (deliberately NOT RLS-scoped, via a plain
`session_scope()` with an explicit `tenant_id` filter), mirroring
`tests/telephony/_cleanup.py`'s own identical scoped/unscoped split for
the identical reason (`product/websites/models.py::Website`'s own module
docstring). Unlike telephony/appointments/marketing, `product.websites`
has no `product.crm` dependency (docs/ADR/0009-...), so this extends
`tests/agency/_cleanup.py` directly rather than `tests/crm/_cleanup.py`.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `tests/*/_cleanup.py`'s own convention.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.agency._cleanup import cleanup_tenant_tree as _cleanup_agency_tenant_tree
from tests.agency._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """`websites.pages` (RLS-scoped) is deleted first, then
    `websites.websites` (unscoped, explicit `tenant_id` filter) --
    mirrors `tests/telephony/_cleanup.py::cleanup_tenant_tree()`'s own
    identical two-pass shape. `pages.website_id` is `ON DELETE CASCADE`
    (`product/websites/models.py::Page`'s own docstring), so the FK would
    handle the ordering automatically; deleting explicitly, in order,
    here is still what actually proves it, not merely relies on it."""
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            session.execute(
                text("DELETE FROM websites.pages WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
        with session_scope() as session:
            session.execute(
                text("DELETE FROM websites.websites WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
    _cleanup_agency_tenant_tree(*tenant_ids_leaf_to_root)
