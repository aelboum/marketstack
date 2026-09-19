"""Reusable message templates (docs/ROADMAP.md Phase 5.5). Literal stored
text only -- no variable-substitution/templating engine. That is the
entire Phase 5.5 requirement ("reusable message templates"); a rendering/
merge-field engine is not asked for and is not built here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.conversations.errors import (
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.models import VALID_CHANNELS, MessageTemplate
from product.conversations.permissions import TEMPLATE_RESOURCE, require


@dataclass(frozen=True, slots=True)
class TemplateView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    channel: str | None
    body: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: MessageTemplate) -> TemplateView:
    return TemplateView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        channel=row.channel,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_valid_channel(channel: str | None) -> None:
    if channel is not None and channel not in VALID_CHANNELS:
        raise ConversationValidationError(
            f"channel must be one of {VALID_CHANNELS} or omitted, got: {channel!r}"
        )


def create_template(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    body: str,
    channel: str | None = None,
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="create")
    _require_valid_channel(channel)
    try:
        with tenant_session_scope(tenant_id) as session:
            row = MessageTemplate(tenant_id=tenant_id, name=name, channel=channel, body=body)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        raise ConversationValidationError(f"a template named {name!r} already exists.") from exc
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.message_template.create",
        resource_type="conversations.message_template",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_template(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, template_id: uuid.UUID
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MessageTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("template", template_id)
        session.expunge(row)
    return _to_view(row)


def list_templates(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[TemplateView]:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MessageTemplate)
                .where(MessageTemplate.tenant_id == tenant_id)
                .order_by(MessageTemplate.name.asc())
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
    body: str | None = None,
    channel: str | None = None,
    _clear_channel: bool = False,
) -> TemplateView:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="update")
    if channel is not None:
        _require_valid_channel(channel)
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MessageTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("template", template_id)
        if body is not None:
            row.body = body
        if channel is not None:
            row.channel = channel
        elif _clear_channel:
            row.channel = None
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.message_template.update",
        resource_type="conversations.message_template",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_template(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, template_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=TEMPLATE_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MessageTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise ConversationReferenceNotFoundError("template", template_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="conversations.message_template.delete",
        resource_type="conversations.message_template",
        resource_id=str(template_id),
        outcome=AuditOutcome.SUCCESS,
    )
