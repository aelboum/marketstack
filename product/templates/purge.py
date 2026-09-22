"""Tenant purge participant for the `templates` schema (mirrors
`product/reputation/purge.py`'s proven pattern). Registered from
`product/api/main.py::create_app()` (see `product/templates/__init__.py`'s
own module docstring for why that wiring is not performed by this phase).

Snapshots are tenant-owned, product-specific configuration bundles, not
financial/security evidence (contrast SaaS-OS's own `core
.billing_subscriptions`, classified `FINANCIAL_RETAIN` in
`core/tenancy/retention.py`) -- a purged tenant's own snapshots are
deleted along with the rest of its operational data. A snapshot
previously *applied* to a different (still-active) tenant is unaffected:
`apply_snapshot()` only ever creates ordinary `crm.pipelines`/
`crm.pipeline_stages` rows there, owned and purged by that tenant's own
lifecycle (`product/crm/purge.py`), with no continuing reference back to
the source snapshot row at all (`docs/ADR/0013-...`'s own "Decision 2":
the payload -- and therefore anything created from it -- carries no
identifier connecting it back to the snapshot or the source tenant).
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.templates.models import Snapshot


class TemplatesDataPurgeParticipant:
    """Deletes every `templates.snapshots` row belonging to the tenant
    being purged. Idempotent -- a second call finds nothing left and
    deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "templates.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            rows = (
                session.execute(
                    select(Snapshot).where(Snapshot.tenant_id == tenant_id).with_for_update()
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
        active_registry.register(TemplatesDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, TemplatesDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise


__all__ = ["TemplatesDataPurgeParticipant", "register"]
