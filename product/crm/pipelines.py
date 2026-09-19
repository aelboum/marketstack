"""Pipeline/stage configuration (docs/ROADMAP.md Phase 4.2).

**Deliberately create+read only in this phase -- no update/delete
endpoint for either pipelines or stages.** The roadmap states no
update/delete requirement for pipeline configuration in Phase 4, and
building one raises a genuinely hard, currently-unspecified question
(what happens to opportunities referencing a deleted stage/pipeline?)
that this phase does not need to answer to satisfy its own acceptance
criteria ("a lead can move through a configurable pipeline"). Deferred,
not overlooked -- see the Phase 4 implementation report.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError
from product.crm.models import Pipeline, PipelineStage
from product.crm.permissions import PIPELINE_RESOURCE, require


@dataclass(frozen=True, slots=True)
class PipelineView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    is_default: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PipelineStageView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    pipeline_id: uuid.UUID
    name: str
    position: int
    is_won: bool
    is_lost: bool
    created_at: datetime


def _pipeline_view(row: Pipeline) -> PipelineView:
    return PipelineView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        is_default=row.is_default,
        created_at=row.created_at,
    )


def _stage_view(row: PipelineStage) -> PipelineStageView:
    return PipelineStageView(
        id=row.id,
        tenant_id=row.tenant_id,
        pipeline_id=row.pipeline_id,
        name=row.name,
        position=row.position,
        is_won=row.is_won,
        is_lost=row.is_lost,
        created_at=row.created_at,
    )


def create_pipeline(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, name: str, is_default: bool = False
) -> PipelineView:
    require(actor_user_id, tenant_id, resource=PIPELINE_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        row = Pipeline(tenant_id=tenant_id, name=name, is_default=is_default)
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.pipeline.create",
        resource_type="crm.pipeline",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _pipeline_view(row)


def list_pipelines(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[PipelineView]:
    require(actor_user_id, tenant_id, resource=PIPELINE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(select(Pipeline).where(Pipeline.tenant_id == tenant_id)).scalars().all()
        )
        for row in rows:
            session.expunge(row)
    return [_pipeline_view(row) for row in rows]


def create_stage(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    *,
    name: str,
    position: int,
    is_won: bool = False,
    is_lost: bool = False,
) -> PipelineStageView:
    require(actor_user_id, tenant_id, resource=PIPELINE_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None or pipeline.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("pipeline", pipeline_id)
        row = PipelineStage(
            tenant_id=tenant_id,
            pipeline_id=pipeline_id,
            name=name,
            position=position,
            is_won=is_won,
            is_lost=is_lost,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.pipeline.stage_create",
        resource_type="crm.pipeline_stage",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"pipeline_id": str(pipeline_id)},
    )
    return _stage_view(row)


def list_stages(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, pipeline_id: uuid.UUID
) -> list[PipelineStageView]:
    require(actor_user_id, tenant_id, resource=PIPELINE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None or pipeline.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("pipeline", pipeline_id)
        rows = (
            session.execute(
                select(PipelineStage)
                .where(
                    PipelineStage.tenant_id == tenant_id, PipelineStage.pipeline_id == pipeline_id
                )
                .order_by(PipelineStage.position.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_stage_view(row) for row in rows]
