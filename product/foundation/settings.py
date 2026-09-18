"""Tenant-scoped key/value settings read/write helpers (docs/ROADMAP.md
Phase 2.1).

Genuinely product-owned: SaaS-OS Core has no generic per-tenant settings
store (confirmed by inspection -- only `core/config/settings.py`, which
is process-level environment configuration, not per-tenant). Named
concrete needs this satisfies (2.1's own acceptance criterion): Agency/
Client provisioning (Phase 3) needs a per-tenant default-pipeline-
template setting; Marketing (Phase 6) needs a per-tenant default sender
name. Neither is built yet -- this phase only proves the mechanism.

Every read/write goes through `infra.db.tenant_session_scope(tenant_id)`
(never a manually tenant_id-filtered unscoped session) so Row-Level
Security -- established by this table's own migration -- is the actual
isolation boundary, not application-level filtering alone.
"""

from __future__ import annotations

import uuid

from infra.db import tenant_session_scope

from product.foundation.models import TenantSetting


def get_setting(tenant_id: uuid.UUID, key: str) -> str | None:
    """Returns the current value of `key` for `tenant_id`, or `None` if
    unset. Never raises for a merely-unset key -- a caller that needs to
    distinguish "unset" from "set to an empty string" should not use an
    empty string as a meaningful value."""
    with tenant_session_scope(tenant_id) as session:
        setting = session.get(TenantSetting, (tenant_id, key))
        return setting.value if setting is not None else None


def set_setting(tenant_id: uuid.UUID, key: str, value: str) -> None:
    """Create or overwrite `key` for `tenant_id`. An upsert (read-then-
    write inside one RLS-scoped session/transaction), not a raw SQL
    `ON CONFLICT` -- consistent with this product's "no raw SQL outside
    infra.db's own chokepoint" discipline (docs/REPOSITORY-STRATEGY.md;
    mirrors saas-os/examples/reference-consumer's own read pattern)."""
    with tenant_session_scope(tenant_id) as session:
        setting = session.get(TenantSetting, (tenant_id, key))
        if setting is None:
            session.add(TenantSetting(tenant_id=tenant_id, key=key, value=value))
        else:
            setting.value = value
