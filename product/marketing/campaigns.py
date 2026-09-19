"""Campaign CRUD and lifecycle (docs/ROADMAP.md Phase 6.1).

Every function follows the shape established by `product/crm
/companies.py`: authorize via `product.marketing.permissions.require()`
first, then the actual `tenant_session_scope()` read/write, then
`core.audit_log.record()` for mutations -- metadata carries only
identifiers, never `name`/`subject`/`body` (message content), per
`docs/ROADMAP.md` Phase 6's own explicit personal-data/audit requirement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.marketing.errors import MarketingReferenceNotFoundError, MarketingValidationError
from product.marketing.models import (
    MAX_CLICK_TARGET_URL_LENGTH,
    STATUS_DRAFT,
    STATUS_SENDING,
    VALID_CAMPAIGN_STATUSES,
    VALID_CHANNELS,
    MarketingCampaign,
    MarketingTemplate,
)
from product.marketing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.marketing.permissions import CAMPAIGN_RESOURCE, require
from product.marketing.segmentation import serialize_segment_query

_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _validate_click_target_url(url: str | None) -> None:
    if url is None:
        return
    if len(url) > MAX_CLICK_TARGET_URL_LENGTH:
        raise MarketingValidationError(
            f"click_target_url exceeds {MAX_CLICK_TARGET_URL_LENGTH} characters."
        )
    if not url.startswith(_ALLOWED_URL_SCHEMES):
        raise MarketingValidationError("click_target_url must be an http:// or https:// URL.")


def _copy_in_template(session, tenant_id: uuid.UUID, template_id: uuid.UUID) -> str:
    """Phase 6.4: a ONE-TIME copy-in of a template's `content` at
    campaign creation/update time -- deliberately NOT a live reference
    re-read at send time. Editing a template later must not
    retroactively change an already-drafted campaign's own stored body;
    this is the explicit, chosen semantics, documented here at its own
    point of use rather than in a separate ADR, since it is a narrow,
    single-module design choice, not a cross-module architecture
    decision. `MarketingTemplate` has no `subject` field of its own
    (templates are body-only, per the roadmap's own minimal scope for
    this subphase) -- an email campaign's `subject` is always supplied
    by the caller directly, never sourced from a template."""
    template = session.get(MarketingTemplate, template_id)
    if template is None or template.tenant_id != tenant_id:
        raise MarketingReferenceNotFoundError("template", template_id)
    return template.content


@dataclass(frozen=True, slots=True)
class CampaignView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    channel: str
    status: str
    subject: str | None
    body: str
    segment_query: str
    template_id: uuid.UUID | None
    click_target_url: str | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: MarketingCampaign) -> CampaignView:
    return CampaignView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        channel=row.channel,
        status=row.status,
        subject=row.subject,
        body=row.body,
        segment_query=row.segment_query,
        template_id=row.template_id,
        click_target_url=row.click_target_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_channel(channel: str) -> None:
    if channel not in VALID_CHANNELS:
        raise MarketingValidationError(f"channel must be one of {VALID_CHANNELS}, got: {channel!r}")


def create_campaign(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    channel: str,
    body: str,
    subject: str | None = None,
    segment_q: str | None = None,
    segment_tag: str | None = None,
    segment_custom_field: list[str] | None = None,
    template_id: uuid.UUID | None = None,
    click_target_url: str | None = None,
) -> CampaignView:
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="create")
    _validate_channel(channel)
    _validate_click_target_url(click_target_url)
    segment_query = serialize_segment_query(
        q=segment_q, tag=segment_tag, custom_field=segment_custom_field
    )
    with tenant_session_scope(tenant_id) as session:
        if template_id is not None:
            body = _copy_in_template(session, tenant_id, template_id)
        if channel == "email" and not subject:
            raise MarketingValidationError("subject is required when channel='email'.")
        row = MarketingCampaign(
            tenant_id=tenant_id,
            name=name,
            channel=channel,
            status=STATUS_DRAFT,
            subject=subject,
            body=body,
            segment_query=segment_query,
            template_id=template_id,
            click_target_url=click_target_url,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.create",
        resource_type="marketing.campaign",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"channel": channel},
    )
    return _to_view(row)


def get_campaign(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> CampaignView:
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaign, campaign_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("campaign", campaign_id)
        session.expunge(row)
    return _to_view(row)


def list_campaigns(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CampaignView]:
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MarketingCampaign)
                .where(MarketingCampaign.tenant_id == tenant_id)
                .order_by(MarketingCampaign.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_campaign(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    segment_q: str | None = None,
    segment_tag: str | None = None,
    segment_custom_field: list[str] | None = None,
    template_id: uuid.UUID | None = None,
    click_target_url: str | None = None,
    _update_segment: bool = False,
    _update_click_target_url: bool = False,
) -> CampaignView:
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="update")
    if _update_click_target_url:
        _validate_click_target_url(click_target_url)
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaign, campaign_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("campaign", campaign_id)
        if row.status != STATUS_DRAFT:
            raise MarketingValidationError(
                f"campaign {campaign_id} cannot be edited once it has left 'draft' "
                f"status (currently {row.status!r})."
            )
        if name is not None:
            row.name = name
        if subject is not None:
            row.subject = subject
        if template_id is not None:
            row.body = _copy_in_template(session, tenant_id, template_id)
            row.template_id = template_id
        elif body is not None:
            row.body = body
        if _update_click_target_url:
            row.click_target_url = click_target_url
        if _update_segment:
            row.segment_query = serialize_segment_query(
                q=segment_q, tag=segment_tag, custom_field=segment_custom_field
            )
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.update",
        resource_type="marketing.campaign",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_campaign(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> None:
    """Only permitted while `status == 'draft'` -- a campaign that has
    started sending (or finished, or was cancelled) is a historical
    record of what this tenant actually did; it must not be deletable
    just because an actor otherwise holds delete authority. A real,
    tested guard, not a UI convention."""
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaign, campaign_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("campaign", campaign_id)
        if row.status != STATUS_DRAFT:
            raise MarketingValidationError(
                f"campaign {campaign_id} cannot be deleted once it has left 'draft' "
                f"status (currently {row.status!r})."
            )
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.delete",
        resource_type="marketing.campaign",
        resource_id=str(campaign_id),
        outcome=AuditOutcome.SUCCESS,
    )


def cancel_campaign(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> CampaignView:
    """Transitions a `'sending'` campaign to `'cancelled'` -- the
    job-level cancellation mechanism `docs/ROADMAP.md` Phase 6.1's own
    Rollback text calls for ("a bad campaign can be paused mid-send").
    This function only flips the status flag; `product/marketing
    /sending.py`'s own job handler is what actually observes it and stops
    processing further recipients -- see that module's docstring."""
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaign, campaign_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("campaign", campaign_id)
        if row.status != STATUS_SENDING:
            raise MarketingValidationError(
                f"campaign {campaign_id} can only be cancelled while 'sending' "
                f"(currently {row.status!r})."
            )
        row.status = "cancelled"
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.cancel",
        resource_type="marketing.campaign",
        resource_id=str(campaign_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


__all__ = [
    "VALID_CAMPAIGN_STATUSES",
    "CampaignView",
    "cancel_campaign",
    "create_campaign",
    "delete_campaign",
    "get_campaign",
    "list_campaigns",
    "update_campaign",
]
