"""Shared teardown helpers for tests/agency/*_integration.py -- mirrors
saas-os's own tests/test_reference_consumer_scenarios_integration.py
`_cleanup_tenant_tree()`/`_cleanup_users()` pattern exactly (same table
list, same leaf-to-root order), reused here rather than re-derived,
since Phase 3's own tests create the identical shape of data (tenants,
memberships, roles, role grants, delegations, denies, support-access
requests) that pattern already proves safe to tear down.

Underscore-prefixed filename -- not itself a test module, mirrors
tests/foundation/_durable_event_subscriber_fixture.py's own convention
so pytest does not try to collect it.
"""

from __future__ import annotations

import uuid

from core.identity import create_user
from core.identity.models import User
from infra.db import (
    build_engine,
    build_session_factory,
    get_migrations_database_config,
    session_scope,
    tenant_session_scope,
)
from sqlalchemy import text


def _admin_session():
    engine = build_engine(get_migrations_database_config())
    factory = build_session_factory(engine)
    return session_scope(session_factory=factory)


def cleanup_tenant_tree(*tenant_ids_leaf_to_root: uuid.UUID) -> None:
    """Delete every row this phase's tests could have created for each
    tenant, leaf tenants first (so a child's own rows are gone before its
    parent tenant row is deleted), then the tenant rows themselves."""
    for tenant_id in tenant_ids_leaf_to_root:
        with _admin_session() as session:
            session.execute(
                text("DELETE FROM core.audit_log WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
        with session_scope() as session:
            session.execute(
                text("DELETE FROM core.invitations WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )
        with tenant_session_scope(tenant_id) as session:
            for table in (
                "delegation_grants",
                "deny_grants",
                "support_access_requests",
                "membership_roles",
                "role_permissions",
                "tenant_memberships",
                "roles",
            ):
                session.execute(
                    text(f"DELETE FROM core.{table} WHERE tenant_id = :t"), {"t": str(tenant_id)}
                )
        with session_scope() as session:
            session.execute(text("DELETE FROM core.tenants WHERE id = :t"), {"t": str(tenant_id)})


def cleanup_users(*user_ids: uuid.UUID) -> None:
    """Deletes core.sessions rows first -- tests/agency/test_routes_
    integration.py issues real sessions (core.identity.sessions
    .issue_session()) for these users, and core.sessions.user_id has no
    ON DELETE CASCADE (confirmed by hitting the resulting
    ForeignKeyViolation directly, not assumed)."""
    with session_scope() as session:
        for user_id in user_ids:
            session.execute(
                text("DELETE FROM core.sessions WHERE user_id = :id"), {"id": str(user_id)}
            )
    with session_scope() as session:
        for user_id in user_ids:
            session.execute(text("DELETE FROM core.users WHERE id = :id"), {"id": str(user_id)})


def make_user() -> User:
    return create_user()
