"""This product's tenant purge participant for `foundation.tenant_settings`
(mirrors saas-os/examples/reference-consumer/reference_consumer/purge.py's
proven pattern exactly). Registered from `product/api/main.py::create_app()`
-- the first genuinely tenant-owned table this product ships (Phase 2.1),
so this is the first phase where a purge participant is actually needed,
not a speculative one (Phase 1's own `product/api/main.py` docstring
explicitly named this as the trigger: "there is no product-owned tenant
data anywhere until a later phase actually writes some").

Deletion, not retention or anonymization, is this table's own deliberate
choice: a tenant setting has no independent value once its tenant is
gone, and carries no PII beyond whatever a later module chooses to store
as a setting value (none does yet).
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.foundation.models import TenantSetting


class TenantSettingsPurgeParticipant:
    """Deletes every `foundation.tenant_settings` row belonging to the
    tenant being purged. Idempotent -- a second call finds nothing left
    and deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "foundation.tenant_settings"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            rows = (
                session.execute(
                    select(TenantSetting)
                    .where(TenantSetting.tenant_id == tenant_id)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.delete(row)


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See reference_consumer/purge.py::register()'s own docstring for
    why re-registering the identically-named participant against the
    same process-wide registry is treated as already-done, not an
    error."""
    active_registry = registry if registry is not None else default_registry()
    try:
        active_registry.register(TenantSettingsPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, TenantSettingsPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise
