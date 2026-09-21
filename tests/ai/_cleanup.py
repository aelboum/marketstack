"""Shared teardown helpers for tests/ai/*_integration.py. Combines
tests/telephony/_cleanup.py's and tests/conversations/_cleanup.py's own
proven table lists (reused directly, not re-derived) since Phase 9's
tools read across all three domains (CRM, Conversations, Telephony) --
mirrors their exact scoped/unscoped split and deletion ordering.

Underscore-prefixed filename -- not itself a test module, mirrors every
other `_cleanup.py` in this test suite.
"""

from __future__ import annotations

import uuid

from infra.db import session_scope, tenant_session_scope
from sqlalchemy import text

from tests.crm._cleanup import cleanup_tenant_tree as _cleanup_crm_tenant_tree
from tests.crm._cleanup import cleanup_users, make_user

__all__ = ["cleanup_tenant_tree", "cleanup_users", "make_user"]

_TELEPHONY_TABLES_LEAF_TO_ROOT = (
    "call_recordings",
    "call_events",
    "calls",
    "phone_number_routing_targets",
)
_TELEPHONY_UNSCOPED_TABLES_LEAF_TO_ROOT = ("phone_numbers",)
_CONVERSATIONS_TABLES_LEAF_TO_ROOT = ("messages", "threads", "message_templates")


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    for tenant_id in tenant_ids_leaf_to_root:
        with tenant_session_scope(tenant_id) as session:
            # docs/ROADMAP.md Phase 9.4's own `ai.tenant_policies` -- one
            # row per tenant, FK to `core.tenants`, so a test tenant that
            # configured a policy cannot otherwise be deleted.
            session.execute(
                text("DELETE FROM ai.tenant_policies WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            for table in _TELEPHONY_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM telephony.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            for table in _CONVERSATIONS_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM conversations.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
        with session_scope() as session:
            for table in _TELEPHONY_UNSCOPED_TABLES_LEAF_TO_ROOT:
                session.execute(
                    text(f"DELETE FROM telephony.{table} WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
    _cleanup_crm_tenant_tree(*tenant_ids_leaf_to_root)
