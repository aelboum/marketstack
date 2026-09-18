"""This product's tenant purge participants for the `white_label` schema
(mirrors saas-os/examples/reference-consumer/reference_consumer/purge.py's
proven pattern). Registered from `product/api/main.py::create_app()`.

Two participants, because the two tables have different isolation
models (docs/ROADMAP.md Phase 2.3/2.4; product/white_label/models.py):
`tenant_branding` is RLS-scoped like any ordinary tenant-owned table, so
its participant reads through `tenant_session_scope()` exactly like
`TenantSettingsPurgeParticipant`. `tenant_domains` is deliberately NOT
RLS-scoped (it must be readable before a tenant context exists) -- its
participant reads through a plain `session_scope()` with an explicit
`WHERE tenant_id = ...` filter instead, which is the correct, sanctioned
substitute for RLS on this one table (the same reasoning
`product/white_label/domains.py::resolve_tenant_for_domain` already
documents for reading it). An orphaned domain mapping pointing at a
purged tenant would otherwise silently keep resolving to a tenant that
no longer principally exists -- deleting it here closes that gap.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, session_scope, tenant_session_scope

from product.white_label.models import TenantBranding, TenantDomain


class TenantBrandingPurgeParticipant:
    """Deletes the tenant's own `white_label.tenant_branding` row, if
    any. Idempotent."""

    @property
    def name(self) -> str:
        return "white_label.tenant_branding"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            row = session.get(TenantBranding, tenant_id)
            if row is not None:
                session.delete(row)


class TenantDomainsPurgeParticipant:
    """Deletes every `white_label.tenant_domains` row mapped to the
    tenant being purged. Idempotent. Uses a plain, untenanted
    `session_scope()` with an explicit `tenant_id` filter -- this table
    carries no RLS policy to rely on instead (see module docstring)."""

    @property
    def name(self) -> str:
        return "white_label.tenant_domains"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with session_scope() as session:
            rows = (
                session.execute(
                    select(TenantDomain)
                    .where(TenantDomain.tenant_id == tenant_id)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.delete(row)


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See reference_consumer/purge.py::register()'s own docstring for
    the re-registration/idempotency reasoning, applied here to both
    participants."""
    active_registry = registry if registry is not None else default_registry()
    for participant in (TenantBrandingPurgeParticipant(), TenantDomainsPurgeParticipant()):
        try:
            active_registry.register(participant)
        except DuplicateTenantPurgeParticipantError:
            if not any(
                isinstance(p, type(participant)) for p in active_registry.list()
            ):  # pragma: no cover -- would mean a *different* type reused this name
                raise
