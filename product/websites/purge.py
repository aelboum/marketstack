"""Tenant purge participants for the `websites` schema (mirrors
`product/telephony/purge.py`'s proven two-participant pattern).
Registered from `product/api/main.py::create_app()`.

**Two participants, not one** -- identical reason to
`product/telephony/purge.py`'s own docstring:

- `WebsitesDataPurgeParticipant` covers `websites.pages` -- ordinary,
  RLS-scoped, via the normal `tenant_session_scope()` path.
- `WebsitesUnscopedDataPurgeParticipant` covers `websites.websites` --
  deliberately NOT RLS-scoped (`product/websites/models.py::Website`'s
  own docstring), so this participant reads through a plain
  `session_scope()` with an explicit `tenant_id` filter instead.

**Pages before websites** -- `pages.website_id` is `ON DELETE CASCADE`
(`product/websites/models.py::Page`'s own docstring), so the FK would
handle this automatically; both participants still run in this order,
leaves before roots, as defense in depth -- identical discipline
`product/telephony/purge.py`'s own docstring already applies for its own
undecided-`ON DELETE` case.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, session_scope, tenant_session_scope

from product.websites.models import Page, Website


class WebsitesDataPurgeParticipant:
    """Deletes every `websites.pages` row belonging to the tenant being
    purged. Idempotent."""

    @property
    def name(self) -> str:
        return "websites.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            rows = (
                session.execute(select(Page).where(Page.tenant_id == tenant_id).with_for_update())
                .scalars()
                .all()
            )
            for row in rows:
                session.delete(row)
            session.flush()


class WebsitesUnscopedDataPurgeParticipant:
    """Deletes every `websites.websites` row mapped to the tenant being
    purged, via a plain, untenanted `session_scope()` with an explicit
    `tenant_id` filter -- this table carries no RLS policy to rely on
    instead. Idempotent."""

    @property
    def name(self) -> str:
        return "websites.unscoped"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with session_scope() as session:
            rows = (
                session.execute(
                    select(Website).where(Website.tenant_id == tenant_id).with_for_update()
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
    for participant in (
        WebsitesDataPurgeParticipant(),
        WebsitesUnscopedDataPurgeParticipant(),
    ):
        try:
            active_registry.register(participant)
        except DuplicateTenantPurgeParticipantError:
            pass


__all__ = ["WebsitesDataPurgeParticipant", "WebsitesUnscopedDataPurgeParticipant", "register"]
