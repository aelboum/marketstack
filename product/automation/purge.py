"""Tenant purge participant for the `automation` schema (mirrors every
other module's own proven pattern -- both `automation.*` tables are
ordinary RLS-scoped, so one participant, not a scoped/unscoped split
(`product/telephony/purge.py`'s own docstring explains when a split is
needed; neither `Workflow` nor `WorkflowRun` here has that need).
Registered from `product/api/main.py::create_app()`.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.automation.models import Workflow, WorkflowRun

_PURGE_ORDER = (WorkflowRun, Workflow)


class AutomationDataPurgeParticipant:
    @property
    def name(self) -> str:
        return "automation.*"

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
    active_registry = registry if registry is not None else default_registry()
    participant = AutomationDataPurgeParticipant()
    try:
        active_registry.register(participant)
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, type(participant)) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise
