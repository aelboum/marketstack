"""Tenant purge participants for the `marketing` schema (mirrors
`product/crm/purge.py`'s proven pattern). Registered from `product/api
/main.py::create_app()`.

**Two participants, not one, because Phase 6.3/6.5 introduced tables with
a different isolation model** -- mirrors `product/white_label/purge.py`'s
own identical two-participant split exactly, for the identical reason:

- `MarketingDataPurgeParticipant` covers every ordinary, RLS-scoped
  `marketing.*` table (`campaign_recipients`, `suppressions`, `campaigns`,
  `form_submissions`, `templates`) via the normal `tenant_session_scope()`
  path. Deletion order: leaves (`campaign_recipients`, `suppressions`,
  `form_submissions`) before roots (`campaigns`, `templates`) -- correct
  regardless of what `ON DELETE` behavior each individual FK happens to
  carry, the same defense-in-depth reasoning `product/crm/purge.py`
  already states.
- `MarketingUnscopedDataPurgeParticipant` covers `forms` and
  `recipient_tracking_tokens` -- deliberately NOT RLS-scoped (migrations
  `0020`/`0023`), so their participant reads through a plain
  `session_scope()` with an explicit `tenant_id` filter instead, mirroring
  `product/white_label/purge.py::TenantDomainsPurgeParticipant`'s own
  identical pattern. An orphaned form/tracking-token mapping pointing at
  a purged tenant would otherwise silently keep resolving to a tenant
  that no longer principally exists.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, session_scope, tenant_session_scope

from product.marketing.models import (
    MarketingCampaign,
    MarketingCampaignRecipient,
    MarketingForm,
    MarketingFormSubmission,
    MarketingRecipientTrackingToken,
    MarketingSuppression,
    MarketingTemplate,
)

_SCOPED_PURGE_ORDER = (
    MarketingCampaignRecipient,
    MarketingSuppression,
    MarketingFormSubmission,
    MarketingCampaign,
    MarketingTemplate,
)

_UNSCOPED_PURGE_ORDER = (
    MarketingRecipientTrackingToken,
    MarketingForm,
)


class MarketingDataPurgeParticipant:
    """Deletes every ordinary, RLS-scoped `marketing.*` row belonging to
    the tenant being purged, in dependency order. Idempotent -- a second
    call finds nothing left in any table and deletes zero rows, never an
    error."""

    @property
    def name(self) -> str:
        return "marketing.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            for model in _SCOPED_PURGE_ORDER:
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


class MarketingUnscopedDataPurgeParticipant:
    """Deletes every `marketing.forms`/`marketing.recipient_tracking_tokens`
    row mapped to the tenant being purged. Idempotent. Uses a plain,
    untenanted `session_scope()` with an explicit `tenant_id` filter --
    these two tables carry no RLS policy to rely on instead (see module
    docstring)."""

    @property
    def name(self) -> str:
        return "marketing.unscoped"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with session_scope() as session:
            for model in _UNSCOPED_PURGE_ORDER:
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
    re-registration/idempotency reasoning, applied here to both
    participants."""
    active_registry = registry if registry is not None else default_registry()
    for participant in (MarketingDataPurgeParticipant(), MarketingUnscopedDataPurgeParticipant()):
        try:
            active_registry.register(participant)
        except DuplicateTenantPurgeParticipantError:
            if not any(
                isinstance(p, type(participant)) for p in active_registry.list()
            ):  # pragma: no cover -- would mean a *different* type reused this name
                raise
