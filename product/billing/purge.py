"""Tenant purge participant for the `billing` schema (mirrors
`product/reputation/purge.py`'s proven pattern). Registered from
`product/api/main.py::create_app()` (see `product/billing/__init__.py`'s
own module docstring for why that wiring is not performed by this phase).

**Only `billing.resale_plans` is purged here** -- `docs/ADR/0012-
resale-billing-ownership-model.md`'s own "Non-Vacuousness / Consequences"
section: `core.billing_subscriptions` is classified `FINANCIAL_RETAIN` and
`core.billing_plans` is classified `GLOBAL_IDENTITY` in SaaS-OS's own
`core/tenancy/retention.py` (read directly, not assumed) -- neither is
tenant-purge-owned by this product, and this participant does not attempt
to duplicate or override that decision. A purged reseller's `ResalePlan`
rows are deleted; the `core.billing.Plan` rows they auto-created become
orphaned but harmless (no other tenant's data references them, and
`core.billing` exposes no `delete_plan()` any caller could use instead).
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.billing.models import ResalePlan


class BillingDataPurgeParticipant:
    """Deletes every `billing.resale_plans` row belonging to the tenant
    being purged. Idempotent -- a second call finds nothing left and
    deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "billing.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            rows = (
                session.execute(
                    select(ResalePlan).where(ResalePlan.tenant_id == tenant_id).with_for_update()
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.delete(row)
            session.flush()


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See `product/reputation/purge.py::register()`'s own docstring for
    the re-registration/idempotency reasoning."""
    active_registry = registry if registry is not None else default_registry()
    try:
        active_registry.register(BillingDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, BillingDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise


__all__ = ["BillingDataPurgeParticipant", "register"]
