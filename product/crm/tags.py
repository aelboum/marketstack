"""Tags (docs/ROADMAP.md Phase 4.4).

`create_tag`/`list_tags` (the tenant's available tag vocabulary) require
`TAG_RESOURCE` -- a tenant-level configuration action, same category as
`crm.custom_field_definition`. Attaching/detaching a tag to a specific
entity reuses that entity's own `update` permission (the consolidation
principle already established for tasks/notes/custom-field-values).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import (
    ENTITY_TYPE_COMPANY,
    ENTITY_TYPE_CONTACT,
    ENTITY_TYPE_OPPORTUNITY,
    Company,
    Contact,
    EntityTag,
    Opportunity,
    Tag,
)
from product.crm.permissions import (
    COMPANY_RESOURCE,
    CONTACT_RESOURCE,
    OPPORTUNITY_RESOURCE,
    TAG_RESOURCE,
    require,
)

_ENTITY_TYPES = (ENTITY_TYPE_CONTACT, ENTITY_TYPE_COMPANY, ENTITY_TYPE_OPPORTUNITY)
_ENTITY_RESOURCE_BY_TYPE = {
    ENTITY_TYPE_CONTACT: CONTACT_RESOURCE,
    ENTITY_TYPE_COMPANY: COMPANY_RESOURCE,
    ENTITY_TYPE_OPPORTUNITY: OPPORTUNITY_RESOURCE,
}
_ENTITY_MODEL_BY_TYPE = {
    ENTITY_TYPE_CONTACT: Contact,
    ENTITY_TYPE_COMPANY: Company,
    ENTITY_TYPE_OPPORTUNITY: Opportunity,
}


def _entity_resource(entity_type: str) -> str:
    resource = _ENTITY_RESOURCE_BY_TYPE.get(entity_type)
    if resource is None:
        raise CrmValidationError(
            f"entity_type must be one of {_ENTITY_TYPES}, got: {entity_type!r}"
        )
    return resource


def _require_entity_in_tenant(
    session, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
):
    model = _ENTITY_MODEL_BY_TYPE[entity_type]
    row = session.get(model, entity_id)
    if row is None or row.tenant_id != tenant_id:
        raise CrmReferenceNotFoundError(entity_type, entity_id)
    return row


@dataclass(frozen=True, slots=True)
class TagView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    created_at: datetime


def _tag_view(row: Tag) -> TagView:
    return TagView(id=row.id, tenant_id=row.tenant_id, name=row.name, created_at=row.created_at)


def create_tag(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, name: str) -> TagView:
    require(actor_user_id, tenant_id, resource=TAG_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        row = Tag(tenant_id=tenant_id, name=name)
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.tag.create",
        resource_type="crm.tag",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _tag_view(row)


def list_tags(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[TagView]:
    require(actor_user_id, tenant_id, resource=TAG_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        rows = session.execute(select(Tag).where(Tag.tenant_id == tenant_id)).scalars().all()
        for row in rows:
            session.expunge(row)
    return [_tag_view(row) for row in rows]


def attach_tag(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> None:
    resource = _entity_resource(entity_type)
    require(actor_user_id, tenant_id, resource=resource, action="update")
    try:
        with tenant_session_scope(tenant_id) as session:
            _require_entity_in_tenant(session, tenant_id, entity_type, entity_id)
            tag = session.get(Tag, tag_id)
            if tag is None or tag.tenant_id != tenant_id:
                raise CrmReferenceNotFoundError("tag", tag_id)
            row = EntityTag(tenant_id=tenant_id, tag_id=tag_id, **{f"{entity_type}_id": entity_id})
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise CrmValidationError(f"tag {tag_id} is already attached to this entity.") from exc
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.tag.attach",
        resource_type=resource,
        resource_id=str(entity_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"tag_id": str(tag_id)},
    )


def detach_tag(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> None:
    resource = _entity_resource(entity_type)
    require(actor_user_id, tenant_id, resource=resource, action="update")
    entity_column = getattr(EntityTag, f"{entity_type}_id")
    with tenant_session_scope(tenant_id) as session:
        row = (
            session.execute(
                select(EntityTag).where(
                    EntityTag.tenant_id == tenant_id,
                    EntityTag.tag_id == tag_id,
                    entity_column == entity_id,
                )
            )
            .scalars()
            .one_or_none()
        )
        if row is None:
            raise CrmReferenceNotFoundError("entity_tag", tag_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.tag.detach",
        resource_type=resource,
        resource_id=str(entity_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"tag_id": str(tag_id)},
    )


def list_tags_for_entity(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, entity_type: str, entity_id: uuid.UUID
) -> list[TagView]:
    resource = _entity_resource(entity_type)
    require(actor_user_id, tenant_id, resource=resource, action="read")
    entity_column = getattr(EntityTag, f"{entity_type}_id")
    with tenant_session_scope(tenant_id) as session:
        tags = (
            session.execute(
                select(Tag)
                .join(EntityTag, EntityTag.tag_id == Tag.id)
                .where(EntityTag.tenant_id == tenant_id, entity_column == entity_id)
            )
            .scalars()
            .all()
        )
        for row in tags:
            session.expunge(row)
    return [_tag_view(row) for row in tags]
