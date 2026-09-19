"""Read-only access to `marketing.campaign_recipients` (docs/ROADMAP.md
Phase 6.1's own "records delivery status per recipient" acceptance
criterion). Mutation of these rows happens exclusively inside
`product/marketing/sending.py`'s own enrollment/job-handler code -- this
module exposes no create/update/delete, only the list a caller (the API,
or a test) needs to observe delivery status.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from infra.db import select, tenant_session_scope

from product.marketing.models import MarketingCampaignRecipient
from product.marketing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.marketing.permissions import CAMPAIGN_RESOURCE, require


@dataclass(frozen=True, slots=True)
class CampaignRecipientView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID | None
    status: str
    sent_at: datetime | None
    error: str | None


def _to_view(row: MarketingCampaignRecipient) -> CampaignRecipientView:
    return CampaignRecipientView(
        id=row.id,
        tenant_id=row.tenant_id,
        campaign_id=row.campaign_id,
        contact_id=row.contact_id,
        status=row.status,
        sent_at=row.sent_at,
        error=row.error,
    )


def list_campaign_recipients(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CampaignRecipientView]:
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MarketingCampaignRecipient)
                .where(
                    MarketingCampaignRecipient.tenant_id == tenant_id,
                    MarketingCampaignRecipient.campaign_id == campaign_id,
                )
                .order_by(MarketingCampaignRecipient.created_at.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]
