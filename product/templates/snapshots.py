"""Snapshot capture and apply (docs/ROADMAP.md Phase 14.1/14.2).

Every mutating/read function authorizes via
`product.templates.permissions.require()` first, then the actual database
access, then `core.audit_log.record()` for mutations -- metadata carries
only identifiers and domain names, never a snapshot's own payload
contents (which, by construction, never contains a secret or a
cross-tenant identifier in the first place -- `docs/ADR/0013-...`'s own
"Decision 2" section -- but is still kept out of audit metadata as a
matter of uniform discipline, not because it would otherwise be unsafe).

**Export reuses `product.crm.pipelines`'s own published functions**
(`docs/ADR/0013-templates-snapshot-scope-and-crm-dependency.md`) -- this
module never constructs or reads a `crm.pipelines`/`crm.pipeline_stages`
row directly. Only `name`/`is_default`/`position`/`is_won`/`is_lost` are
copied into the payload -- never `id`/`tenant_id`/`pipeline_id`
(`product/templates/models.py`'s own module docstring: "payload never
contains an identifier of any kind").

**`apply_snapshot()` is not fully transactional across the whole
operation** -- `docs/ADR/0013-...`'s own "Decision 3" section explains
why (CRM's own `pipelines.py` deliberately has no delete to compensate
with) and what is done instead: every validation that can fail
(authorization on both tenants, schema-version support, payload
structure) runs before the first `create_pipeline()`/`create_stage()`
call, so the only residual failure window is a genuine infrastructure
fault mid-loop -- disclosed, not hidden, and still produces a `FAILURE`
audit entry rather than silently leaving a partial result unexplained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.pipelines import create_pipeline, create_stage, list_pipelines, list_stages
from product.foundation.events import Event, publish
from product.templates.errors import SnapshotApplyError, SnapshotNotFoundError
from product.templates.models import Snapshot
from product.templates.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.templates.permissions import SNAPSHOT_RESOURCE, require
from product.templates.schema import (
    CURRENT_SCHEMA_VERSION,
    DOMAIN_CRM_PIPELINES,
    validate_domains,
    validate_payload_shape,
    validate_schema_version,
)

SNAPSHOT_CREATED_EVENT_TYPE = "templates.snapshot.created"
SNAPSHOT_CREATED_EVENT_VERSION = 1
SNAPSHOT_APPLIED_EVENT_TYPE = "templates.snapshot.applied"
SNAPSHOT_APPLIED_EVENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class SnapshotView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    schema_version: int
    included_domains: list
    payload: dict
    created_by_user_id: uuid.UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotApplyResult:
    snapshot_id: uuid.UUID
    target_tenant_id: uuid.UUID
    created_counts: dict[str, int]


def _to_view(row: Snapshot) -> SnapshotView:
    return SnapshotView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        schema_version=row.schema_version,
        included_domains=row.included_domains,
        payload=row.payload,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


# --- Export (domain-specific) ----------------------------------------------------


def _export_crm_pipelines(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[dict]:
    exported = []
    for pipeline in list_pipelines(actor_user_id, tenant_id):
        stages = list_stages(actor_user_id, tenant_id, pipeline.id)
        exported.append(
            {
                "name": pipeline.name,
                "is_default": pipeline.is_default,
                "stages": [
                    {
                        "name": stage.name,
                        "position": stage.position,
                        "is_won": stage.is_won,
                        "is_lost": stage.is_lost,
                    }
                    for stage in stages
                ],
            }
        )
    return exported


_EXPORTERS = {DOMAIN_CRM_PIPELINES: _export_crm_pipelines}


# --- Apply (domain-specific) ------------------------------------------------------


def _apply_crm_pipelines(
    actor_user_id: uuid.UUID, target_tenant_id: uuid.UUID, entries: list[dict]
) -> int:
    created = 0
    for entry in entries:
        pipeline = create_pipeline(
            actor_user_id, target_tenant_id, name=entry["name"], is_default=entry["is_default"]
        )
        for stage in entry["stages"]:
            create_stage(
                actor_user_id,
                target_tenant_id,
                pipeline.id,
                name=stage["name"],
                position=stage["position"],
                is_won=stage["is_won"],
                is_lost=stage["is_lost"],
            )
        created += 1
    return created


_APPLIERS = {DOMAIN_CRM_PIPELINES: _apply_crm_pipelines}


def create_snapshot(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    description: str | None = None,
    domains: list[str],
) -> SnapshotView:
    require(actor_user_id, tenant_id, resource=SNAPSHOT_RESOURCE, action="create")
    validated_domains = validate_domains(domains)

    payload = {domain: _EXPORTERS[domain](actor_user_id, tenant_id) for domain in validated_domains}
    validate_payload_shape(CURRENT_SCHEMA_VERSION, validated_domains, payload)

    snapshot_id = uuid.uuid4()
    with tenant_session_scope(tenant_id) as session:
        session.add(
            Snapshot(
                id=snapshot_id,
                tenant_id=tenant_id,
                name=name,
                description=description,
                schema_version=CURRENT_SCHEMA_VERSION,
                included_domains=validated_domains,
                payload=payload,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Snapshot, snapshot_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="templates.snapshot.created",
        resource_type="templates.snapshot",
        resource_id=str(snapshot_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"included_domains": validated_domains},
    )
    publish(
        Event(
            type=SNAPSHOT_CREATED_EVENT_TYPE,
            version=SNAPSHOT_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"snapshot_id": str(snapshot_id), "included_domains": validated_domains},
        )
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, snapshot_id: uuid.UUID) -> Snapshot:
    row = session.get(Snapshot, snapshot_id)
    if row is None or row.tenant_id != tenant_id:
        raise SnapshotNotFoundError(snapshot_id)
    return row


def get_snapshot(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, snapshot_id: uuid.UUID
) -> SnapshotView:
    require(actor_user_id, tenant_id, resource=SNAPSHOT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, snapshot_id)
        session.expunge(row)
    return _to_view(row)


def list_snapshots(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[SnapshotView]:
    require(actor_user_id, tenant_id, resource=SNAPSHOT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Snapshot)
                .where(Snapshot.tenant_id == tenant_id)
                .order_by(Snapshot.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def apply_snapshot(
    actor_user_id: uuid.UUID,
    source_tenant_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    target_tenant_id: uuid.UUID,
) -> SnapshotApplyResult:
    """Applies `snapshot_id` (owned by `source_tenant_id`) to
    `target_tenant_id`, creating fresh CRM pipelines/stages there. See
    module docstring for the transactionality disclosure."""
    require(actor_user_id, source_tenant_id, resource=SNAPSHOT_RESOURCE, action="read")
    with tenant_session_scope(source_tenant_id) as session:
        row = _get_owned_row(session, source_tenant_id, snapshot_id)
        session.expunge(row)
    require(actor_user_id, target_tenant_id, resource=SNAPSHOT_RESOURCE, action="apply")

    # All validation that can fail runs before any write -- see module
    # docstring's own transactionality disclosure.
    validate_schema_version(row.schema_version)
    validate_payload_shape(row.schema_version, row.included_domains, row.payload)

    created_counts: dict[str, int] = {}
    try:
        for domain in row.included_domains:
            created_counts[domain] = _APPLIERS[domain](
                actor_user_id, target_tenant_id, row.payload[domain]
            )
    except Exception as exc:
        record(
            tenant_id=target_tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="templates.snapshot.apply_failed",
            resource_type="templates.snapshot",
            resource_id=str(snapshot_id),
            outcome=AuditOutcome.FAILURE,
            metadata={"source_tenant_id": str(source_tenant_id), "partial": created_counts},
        )
        raise SnapshotApplyError(type(exc).__name__) from exc

    record(
        tenant_id=target_tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="templates.snapshot.applied",
        resource_type="templates.snapshot",
        resource_id=str(snapshot_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"source_tenant_id": str(source_tenant_id), "created_counts": created_counts},
    )
    publish(
        Event(
            type=SNAPSHOT_APPLIED_EVENT_TYPE,
            version=SNAPSHOT_APPLIED_EVENT_VERSION,
            tenant_id=str(target_tenant_id),
            payload={
                "snapshot_id": str(snapshot_id),
                "source_tenant_id": str(source_tenant_id),
                "created_counts": created_counts,
            },
        )
    )
    return SnapshotApplyResult(
        snapshot_id=snapshot_id, target_tenant_id=target_tenant_id, created_counts=created_counts
    )


__all__ = [
    "SNAPSHOT_APPLIED_EVENT_TYPE",
    "SNAPSHOT_CREATED_EVENT_TYPE",
    "SnapshotApplyResult",
    "SnapshotView",
    "apply_snapshot",
    "create_snapshot",
    "get_snapshot",
    "list_snapshots",
]
