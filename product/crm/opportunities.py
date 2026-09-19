"""Opportunity CRUD and stage transitions (docs/ROADMAP.md Phase 4.2).

`amount`, if supplied to `create_opportunity`/`update_opportunity`, is a
`product.foundation.values.Money` instance -- converted to
`(amount_minor_units, amount_currency)` at this module's own boundary,
never stored as a `Decimal`/`float` (`crm.opportunities`'s own `CHECK`
constraint additionally enforces both-or-neither at the database level).

`change_stage()` is a dedicated action, not folded into `update_opportunity()`
-- per docs/ROADMAP.md Phase 4.2, a stage change is the one CRM mutation
that also publishes a `crm.opportunity.stage_changed` domain event
(`product.foundation.events`, the **synchronous, in-process** `publish()`
variant -- nothing subscribes yet, per the roadmap's own text that
Automation/Reporting are future phases, so there is no current
requirement for this event to survive a process restart; switching to
`publish_durable()` later is a call-site-only change if a future
subscriber needs it). Only non-sensitive identifiers go in the audit
metadata and event payload -- never the opportunity's own name or amount,
which are business-record contents, not the "what happened, by whom"
audit/event contract.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError
from product.crm.models import ENTITY_TYPE_OPPORTUNITY, Company, Contact, Opportunity, PipelineStage
from product.crm.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.crm.permissions import OPPORTUNITY_RESOURCE, require
from product.crm.search import apply_custom_field_filters, apply_tag_filter, apply_text_search
from product.foundation.events import Event, publish
from product.foundation.values import Money

STAGE_CHANGED_EVENT_TYPE = "crm.opportunity.stage_changed"
STAGE_CHANGED_EVENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class OpportunityView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    amount: Money | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: Opportunity) -> OpportunityView:
    amount = (
        Money(minor_units=row.amount_minor_units, currency=row.amount_currency)
        if row.amount_minor_units is not None and row.amount_currency is not None
        else None
    )
    return OpportunityView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        contact_id=row.contact_id,
        company_id=row.company_id,
        pipeline_id=row.pipeline_id,
        stage_id=row.stage_id,
        amount=amount,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_stage_in_tenant(session, tenant_id: uuid.UUID, stage_id: uuid.UUID) -> PipelineStage:
    stage = session.get(PipelineStage, stage_id)
    if stage is None or stage.tenant_id != tenant_id:
        raise CrmReferenceNotFoundError("pipeline_stage", stage_id)
    return stage


def create_opportunity(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    amount: Money | None = None,
) -> OpportunityView:
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        stage = _require_stage_in_tenant(session, tenant_id, stage_id)
        if stage.pipeline_id != pipeline_id:
            raise CrmReferenceNotFoundError("pipeline_stage", stage_id)
        if contact_id is not None:
            contact = session.get(Contact, contact_id)
            if contact is None or contact.tenant_id != tenant_id:
                raise CrmReferenceNotFoundError("contact", contact_id)
        if company_id is not None:
            company = session.get(Company, company_id)
            if company is None or company.tenant_id != tenant_id:
                raise CrmReferenceNotFoundError("company", company_id)
        row = Opportunity(
            tenant_id=tenant_id,
            name=name,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            contact_id=contact_id,
            company_id=company_id,
            amount_minor_units=amount.minor_units if amount is not None else None,
            amount_currency=amount.currency if amount is not None else None,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.opportunity.create",
        resource_type="crm.opportunity",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_opportunity(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> OpportunityView:
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Opportunity, opportunity_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("opportunity", opportunity_id)
        session.expunge(row)
    return _to_view(row)


def list_opportunities(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] | None = None,
) -> list[OpportunityView]:
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        stmt = select(Opportunity).where(Opportunity.tenant_id == tenant_id)
        stmt = apply_text_search(stmt, Opportunity, (Opportunity.name,), q)
        stmt = apply_tag_filter(stmt, Opportunity, ENTITY_TYPE_OPPORTUNITY, tenant_id, tag)
        stmt = apply_custom_field_filters(
            stmt,
            Opportunity,
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE_OPPORTUNITY,
            custom_field_params=custom_field,
            session=session,
        )
        rows = (
            session.execute(
                stmt.order_by(Opportunity.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_opportunity(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    name: str | None = None,
    amount: Money | None = None,
) -> OpportunityView:
    """Ordinary field updates only -- never the stage (use
    `change_stage()`, which carries the audit+event treatment a stage
    transition specifically requires)."""
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Opportunity, opportunity_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("opportunity", opportunity_id)
        if name is not None:
            row.name = name
        if amount is not None:
            row.amount_minor_units = amount.minor_units
            row.amount_currency = amount.currency
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.opportunity.update",
        resource_type="crm.opportunity",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_opportunity(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> None:
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Opportunity, opportunity_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("opportunity", opportunity_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.opportunity.delete",
        resource_type="crm.opportunity",
        resource_id=str(opportunity_id),
        outcome=AuditOutcome.SUCCESS,
    )


def change_stage(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    new_stage_id: uuid.UUID,
) -> OpportunityView:
    require(actor_user_id, tenant_id, resource=OPPORTUNITY_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Opportunity, opportunity_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("opportunity", opportunity_id)
        new_stage = _require_stage_in_tenant(session, tenant_id, new_stage_id)
        if new_stage.pipeline_id != row.pipeline_id:
            raise CrmReferenceNotFoundError("pipeline_stage", new_stage_id)
        from_stage_id = row.stage_id
        row.stage_id = new_stage_id
        session.flush()
        session.refresh(row)
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.opportunity.stage_changed",
        resource_type="crm.opportunity",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"from_stage_id": str(from_stage_id), "to_stage_id": str(new_stage_id)},
    )
    publish(
        Event(
            type=STAGE_CHANGED_EVENT_TYPE,
            version=STAGE_CHANGED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "opportunity_id": str(row.id),
                "pipeline_id": str(row.pipeline_id),
                "from_stage_id": str(from_stage_id),
                "to_stage_id": str(new_stage_id),
            },
        )
    )
    return _to_view(row)
