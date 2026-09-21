"""Tenant purge participant for the `ai` schema (docs/ROADMAP.md Phase
9.4). Mirrors `product/telephony/purge.py`'s own proven pattern.
Registered from `product/api/main.py::create_app()`.

One ordinary, RLS-scoped table (`ai.tenant_policies`, at most one row per
tenant), so one participant via the normal `tenant_session_scope()` path
-- no unscoped counterpart is needed here.

Purging the policy row restores the tenant to the default-deny state
(`product/ai/policy.py::resolve_tenant_ai_policy()` returns `None` for a
tenant with no row), which is the correct terminal posture for a tenant
whose data is being erased: no residual approval can outlive the tenant.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.ai.models import TenantAIPolicy

_PURGE_ORDER = (TenantAIPolicy,)


class AIDataPurgeParticipant:
    """Deletes every `ai.*` row belonging to the tenant being purged.
    Idempotent."""

    @property
    def name(self) -> str:
        return "ai.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            for model in _PURGE_ORDER:
                rows = (
                    session.execute(
                        select(model).where(model.tenant_id == tenant_id).with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    session.delete(row)
                session.flush()


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See `product/crm/purge.py::register()`'s own docstring for the
    re-registration/idempotency reasoning."""
    active_registry = registry if registry is not None else default_registry()
    try:
        active_registry.register(AIDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        pass


__all__ = ["AIDataPurgeParticipant", "register"]
