"""Tenant purge participant for the `reputation` schema (mirrors
`product/crm/purge.py`'s proven "one consolidated participant, explicit
child-before-parent order" pattern). Registered from `product/api/main.py
::create_app()`.

**One consolidated participant for all three `reputation.*` tables** --
`reputation.review_responses` references `reputation.reviews`, which
references `reputation.review_requests`. Deletion order is handled
explicitly in a single `purge_tenant_data()` call, children before
parents -- correct regardless of each FK's own `ON DELETE` behavior
(`review_responses.review_id` is in fact `CASCADE`, `reviews
.review_request_id` is `SET NULL`, so Postgres would not even need this
ordering to avoid an FK violation; the explicit order is kept anyway so
this participant's own correctness does not silently depend on that
detail, mirroring `product/crm/purge.py`'s own identical reasoning), and
not dependent on inter-participant ordering
`core.tenancy.purge_participants.TenantPurgeParticipantRegistry` does not
promise.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.reputation.models import Review, ReviewRequest, ReviewResponse

_PURGE_ORDER = (
    ReviewResponse,
    Review,
    ReviewRequest,
)


class ReputationDataPurgeParticipant:
    """Deletes every `reputation.*` row belonging to the tenant being
    purged, in dependency order. Idempotent -- a second call finds
    nothing left in any table and deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "reputation.*"

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
        active_registry.register(ReputationDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, ReputationDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise


__all__ = ["ReputationDataPurgeParticipant", "register"]
