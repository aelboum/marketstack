"""Audience segmentation (docs/ROADMAP.md Phase 6.1's own "audience
segmentation query" objective).

**The one place in `product/marketing/` that imports across the
`crm`/`marketing` sibling boundary** -- see `docs/ADR/0005-marketing-
depends-on-crm.md` for the full architecture decision. Only
`product.crm.contacts.list_contacts` is imported here (CRM's own
published, read-oriented, already-authorizing service function) -- never
`product.crm.models`, never any other `product.crm.*` submodule, and
never any other product module.

**`segment_query` shape** -- a small, explicit JSON object, never raw SQL
or a free-form query language, reusing `product.crm.contacts
.list_contacts()`'s own existing, already-injection-safe filter
parameters directly (see `product/crm/search.py`'s own module docstring
for the parameterized-query discipline those parameters already follow --
this module adds no new query-construction logic of its own, it only
unpacks a stored dict into the identical keyword arguments an ordinary
CRM API call would use):

    {"q": "<optional substring>", "tag": "<optional exact tag name>",
     "custom_field": ["<definition_id>:<value>", ...],
     "engagement": {"opened_campaign_id": "<uuid>"} |
                   {"clicked_campaign_id": "<uuid>"}}

All keys optional; `{}` (the default) matches every contact in the
tenant. `custom_field` is a *list* of `"<definition_id>:<value>"`
strings, matching `list_contacts()`'s own parameter shape exactly (not a
single dict -- CRM's own filtering already supports multiple custom-field
constraints ANDed together).

**`engagement` (Phase 6.5's own "segmentation criteria expanded to
include engagement history" objective)** -- "contacts who opened/clicked
a specific prior campaign." Resolved by querying
`marketing.campaign_recipients` directly, this module's own sibling
table, not a cross-module read (unlike `q`/`tag`/`custom_field`, which
still go through `product.crm.contacts.list_contacts()` exactly as
established above). Applied as a post-filter, intersecting the CRM-based
result with the set of contact ids that have a matching
`campaign_recipients` row -- correct for this phase's expected data
volumes; a large-scale deployment might instead want to push this down
as a SQL join, a genuine future optimization, not a correctness gap
(every matching contact is still found, just via an extra round trip).

**No second authorization check for the CRM-read half**: `resolve_segment()`
calls `list_contacts()`, which already calls `product.crm.permissions
.require(..., CONTACT_RESOURCE, "read")` internally -- an actor who
cannot read this tenant's contacts gets `CrmAccessDeniedError` from that
call, propagated unchanged. This function does not additionally guard the
CRM read with a `marketing.*` permission; the caller (`product/marketing
/sending.py::start_campaign_send()`) is responsible for its own
`marketing.campaign` permission check before calling this at all.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from infra.db import select, tenant_session_scope

from product.crm.contacts import ContactView, list_contacts
from product.marketing.errors import MarketingValidationError
from product.marketing.models import MarketingCampaignRecipient

# Walks list_contacts() one page at a time until a short page (fewer rows
# than requested) signals the end -- never a caller-supplied, unbounded
# limit; MAX_PAGE_SIZE (product.crm.pagination's own bound, which
# list_contacts() itself enforces via clamp_limit()) is the per-page size
# used here regardless of how many contacts ultimately match.
_SEGMENT_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class EngagementFilter:
    opened_campaign_id: uuid.UUID | None = None
    clicked_campaign_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SegmentQuery:
    q: str | None = None
    tag: str | None = None
    custom_field: tuple[str, ...] | None = None
    engagement: EngagementFilter | None = None


def parse_segment_query(raw: str) -> SegmentQuery:
    """Deserialize the stored `marketing.campaigns.segment_query` text
    column into a `SegmentQuery`. Raises `MarketingValidationError` for a
    malformed stored value (should not happen in practice --
    `serialize_segment_query()` is the only writer -- but a service
    function reading this back must not simply crash on an unexpected
    shape)."""
    try:
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError) as exc:
        raise MarketingValidationError(f"segment_query is not valid JSON: {raw!r}") from exc
    if not isinstance(data, dict):
        raise MarketingValidationError(f"segment_query must be a JSON object, got: {raw!r}")
    custom_field = data.get("custom_field")
    if custom_field is not None and not isinstance(custom_field, list):
        raise MarketingValidationError("segment_query.custom_field must be a list of strings.")
    engagement_raw = data.get("engagement")
    engagement = None
    if engagement_raw:
        if not isinstance(engagement_raw, dict):
            raise MarketingValidationError("segment_query.engagement must be a JSON object.")
        opened = engagement_raw.get("opened_campaign_id")
        clicked = engagement_raw.get("clicked_campaign_id")
        engagement = EngagementFilter(
            opened_campaign_id=uuid.UUID(str(opened)) if opened else None,
            clicked_campaign_id=uuid.UUID(str(clicked)) if clicked else None,
        )
    return SegmentQuery(
        q=data.get("q"),
        tag=data.get("tag"),
        custom_field=tuple(custom_field) if custom_field else None,
        engagement=engagement,
    )


def serialize_segment_query(
    *,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] | None = None,
    opened_campaign_id: uuid.UUID | None = None,
    clicked_campaign_id: uuid.UUID | None = None,
) -> str:
    """The one writer of the stored `segment_query` column -- a plain
    `json.dumps` of the caller-supplied filter, never a caller-supplied
    raw string stored verbatim (the caller passes structured fields, not
    a pre-built JSON blob, so this function is the single place that
    decides the on-disk shape)."""
    engagement = None
    if opened_campaign_id or clicked_campaign_id:
        engagement = {
            "opened_campaign_id": str(opened_campaign_id) if opened_campaign_id else None,
            "clicked_campaign_id": str(clicked_campaign_id) if clicked_campaign_id else None,
        }
    return json.dumps(
        {"q": q, "tag": tag, "custom_field": custom_field or None, "engagement": engagement}
    )


def resolve_segment(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, segment_query: SegmentQuery
) -> list[ContactView]:
    """Every contact in `tenant_id` matching `segment_query`, walking
    every page of `product.crm.contacts.list_contacts()` (never a single,
    caller-bounded page -- a campaign send needs the *complete* matching
    set) until a short page signals exhaustion."""
    contacts: list[ContactView] = []
    offset = 0
    while True:
        page = list_contacts(
            actor_user_id,
            tenant_id,
            limit=_SEGMENT_PAGE_SIZE,
            offset=offset,
            q=segment_query.q,
            tag=segment_query.tag,
            custom_field=list(segment_query.custom_field) if segment_query.custom_field else None,
        )
        contacts.extend(page)
        if len(page) < _SEGMENT_PAGE_SIZE:
            break
        offset += _SEGMENT_PAGE_SIZE

    if segment_query.engagement is not None:
        engaged_ids = _resolve_engaged_contact_ids(tenant_id, segment_query.engagement)
        contacts = [c for c in contacts if c.id in engaged_ids]
    return contacts


def _resolve_engaged_contact_ids(
    tenant_id: uuid.UUID, engagement: EngagementFilter
) -> set[uuid.UUID]:
    """Contacts with a `marketing.campaign_recipients` row proving they
    opened/clicked the named campaign -- this module's own sibling
    table, queried directly (not through CRM, not a cross-module read)."""
    with tenant_session_scope(tenant_id) as session:
        stmt = select(MarketingCampaignRecipient.contact_id).where(
            MarketingCampaignRecipient.tenant_id == tenant_id,
            MarketingCampaignRecipient.contact_id.is_not(None),
        )
        if engagement.opened_campaign_id is not None:
            stmt = stmt.where(
                MarketingCampaignRecipient.campaign_id == engagement.opened_campaign_id,
                MarketingCampaignRecipient.opened_at.is_not(None),
            )
        elif engagement.clicked_campaign_id is not None:
            stmt = stmt.where(
                MarketingCampaignRecipient.campaign_id == engagement.clicked_campaign_id,
                MarketingCampaignRecipient.clicked_at.is_not(None),
            )
        else:
            return set()
        rows = session.execute(stmt).scalars().all()
    # The WHERE clause above already excludes NULL contact_id rows --
    # this comprehension only narrows the static type to match (pyright
    # cannot infer that from the runtime filter alone).
    return {row for row in rows if row is not None}
