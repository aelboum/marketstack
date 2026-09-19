"""Landing page and campaign templates (docs/ROADMAP.md Phase 6.4).

`template_type="landing_page"` is a stored content blob only -- NOT a
page builder or rendering engine. Phase 11 (Websites) owns visual page
building; this phase covers template reuse for campaigns/forms
specifically, per the roadmap's own explicit scope boundary. Do not
misread this module as more than it is.

`clone_template()` copies `content`/`template_type` under a new `name` --
a plain data copy, not a live reference back to the original.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.marketing.errors import MarketingReferenceNotFoundError, MarketingValidationError
from product.marketing.models import (
    MAX_TEMPLATE_CONTENT_LENGTH,
    MAX_TEMPLATE_NAME_LENGTH,
    VALID_TEMPLATE_TYPES,
    MarketingTemplate,
)
from product.marketing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.marketing.permissions import TEMPLATE_RESOURCE, require


@dataclass(frozen=True, slots=True)
class TemplateView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    template_type: str
    content: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: MarketingTemplate) -> TemplateView:
    return TemplateView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        template_type=row.template_type,
        content=row.content,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate(name: str, template_type: str, content: str) -> None:
    if template_type not in VALID_TEMPLATE_TYPES:
        raise MarketingValidationError(
            f"template_type must be one of {VALID_TEMPLATE_TYPES}, got: {template_type!r}"
        )
    if len(name) > MAX_TEMPLATE_NAME_LENGTH:
        raise MarketingValidationError(f"name exceeds {MAX_TEMPLATE_NAME_LENGTH} characters.")
    if len(content) > MAX_TEMPLATE_CONTENT_LENGTH:
        raise MarketingValidationError(f"content exceeds {MAX_TEMPLATE_CONTENT_LENGTH} characters.")


def create_template(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    template_type: str,
    content: str,
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="create")
    _validate(name, template_type, content)
    try:
        with tenant_session_scope(tenant_id) as session:
            row = MarketingTemplate(
                tenant_id=tenant_id, name=name, template_type=template_type, content=content
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        raise MarketingValidationError(f"a template named {name!r} already exists.") from exc
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.template.create",
        resource_type="marketing.template",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"template_type": template_type},
    )
    return _to_view(row)


def get_template(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, template_id: uuid.UUID
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("template", template_id)
        session.expunge(row)
    return _to_view(row)


def list_templates(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[TemplateView]:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MarketingTemplate)
                .where(MarketingTemplate.tenant_id == tenant_id)
                .order_by(MarketingTemplate.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_template(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    content: str | None = None,
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("template", template_id)
        if name is not None:
            row.name = name
        if content is not None:
            row.content = content
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.template.update",
        resource_type="marketing.template",
        resource_id=str(template_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_template(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, template_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("template", template_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.template.delete",
        resource_type="marketing.template",
        resource_id=str(template_id),
        outcome=AuditOutcome.SUCCESS,
    )


def clone_template(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, template_id: uuid.UUID, *, new_name: str
) -> TemplateView:
    """Copies `content`/`template_type` under `new_name` -- a plain data
    copy, never a live reference to the original. Rejects a `new_name`
    that collides with an existing template with a clean
    `MarketingValidationError`, not a raw `IntegrityError`."""
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        original = session.get(MarketingTemplate, template_id)
        if original is None or original.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("template", template_id)
        template_type = original.template_type
        content = original.content
    return create_template(
        actor_user_id, tenant_id, name=new_name, template_type=template_type, content=content
    )
