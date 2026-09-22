"""The conversations API (docs/ROADMAP.md Phase 5), mounted under
`/v1/conversations` in `product/api/main.py`.

**Ingress dependency choice -- read `docs/ADR/0002-agency-cross-tenant-
route-authorization.md`'s Phase 4 addendum before changing this.** Every
route below uses `api.dependencies.get_current_actor`, not
`api.dependencies.get_tenant_context`/`require_permission()` -- the
identical reasoning already applied to `product/crm/routes.py`: an agency
owner reaching a client's conversations only via inherited `SUBTREE` role
has no direct membership at that client tenant, so `get_tenant_context()`
would 404 them. Every `product/conversations/*.py` service function
performs its own `core.rbac.can()` check via
`product.conversations.permissions.require()` before touching any
`conversations.*` row.

**Non-enumeration**: `ConversationAccessDeniedError` and
`ConversationReferenceNotFoundError` both map to the identical `404`
shape `api.errors.not_found()` uses elsewhere in this platform.
`ConversationValidationError` and `core.email`'s own configuration/
provider/address errors are client/server input errors, mapped to a
plain `400` instead.

**Field length bounds are enforced at this Pydantic layer, not only the
database** -- Phase 4's own report flagged relying on DB column limits
alone as a minor gap; every free-text request field below carries an
explicit `max_length`.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.conversations.email_sending import send_email_message
from product.conversations.errors import (
    ConversationAccessDeniedError,
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.inbox import list_inbox
from product.conversations.messages import create_message, list_messages
from product.conversations.models import MAX_MESSAGE_BODY_LENGTH
from product.conversations.pagination import DEFAULT_PAGE_SIZE
from product.conversations.templates import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from product.conversations.threads import (
    assign_thread,
    create_thread,
    delete_thread,
    get_thread,
    list_threads,
    update_thread,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    ConversationAccessDeniedError,
    ConversationReferenceNotFoundError,
)
_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    ConversationValidationError,
    EmailConfigurationError,
    EmailProviderError,
    InvalidEmailAddressError,
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request bodies -----------------------------------------------------


class CreateThreadRequest(BaseModel):
    contact_id: uuid.UUID
    channel: str


class UpdateThreadRequest(BaseModel):
    channel: str | None = None


class AssignThreadRequest(BaseModel):
    assignee_user_id: uuid.UUID


class CreateMessageRequest(BaseModel):
    direction: str
    is_internal_note: bool = False
    body: str = Field(max_length=MAX_MESSAGE_BODY_LENGTH)


class SendEmailRequest(BaseModel):
    to_email: str
    subject: str = Field(max_length=255)
    body: str = Field(max_length=MAX_MESSAGE_BODY_LENGTH)


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=255)
    body: str = Field(max_length=MAX_MESSAGE_BODY_LENGTH)
    channel: str | None = None


class UpdateTemplateRequest(BaseModel):
    body: str | None = Field(default=None, max_length=MAX_MESSAGE_BODY_LENGTH)
    channel: str | None = None


def _thread_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "channel": view.channel,
        "assigned_to_user_id": str(view.assigned_to_user_id) if view.assigned_to_user_id else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _inbox_item_dict(view) -> dict[str, object]:
    return {
        "thread_id": str(view.thread_id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "channel": view.channel,
        "assigned_to_user_id": str(view.assigned_to_user_id) if view.assigned_to_user_id else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
        "last_message_preview": view.last_message_preview,
        "last_message_at": view.last_message_at.isoformat() if view.last_message_at else None,
        "last_message_direction": view.last_message_direction,
        "last_message_is_internal_note": view.last_message_is_internal_note,
        "needs_reply": view.needs_reply,
    }


def _message_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "thread_id": str(view.thread_id),
        "direction": view.direction,
        "is_internal_note": view.is_internal_note,
        "body": view.body,
        "author_user_id": str(view.author_user_id) if view.author_user_id else None,
        "sequence": view.sequence,
        "created_at": view.created_at.isoformat(),
    }


def _template_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "channel": view.channel,
        "body": view.body,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


# --- Unified Inbox (docs/ROADMAP.md Phase 30) ------------------------------


@router.get("/tenants/{tenant_id}/inbox")
def list_inbox_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    assigned: str | None = None,
    channel: str | None = None,
    needs_reply: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    if assigned is not None and assigned not in ("me", "unassigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="assigned must be 'me' or 'unassigned' if provided.",
        )
    return [
        _inbox_item_dict(v)
        for v in _call(
            list_inbox,
            actor_id,
            tenant_id,
            assigned=assigned,
            channel=channel,
            needs_reply=needs_reply,
            limit=limit,
            offset=offset,
        )
    ]


# --- Threads --------------------------------------------------------------


@router.post("/tenants/{tenant_id}/threads", status_code=status.HTTP_201_CREATED)
def create_thread_route(
    tenant_id: uuid.UUID,
    body: CreateThreadRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _thread_dict(
        _call(create_thread, actor_id, tenant_id, contact_id=body.contact_id, channel=body.channel)
    )


@router.get("/tenants/{tenant_id}/threads")
def list_threads_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _thread_dict(v)
        for v in _call(list_threads, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/threads/{thread_id}")
def get_thread_route(
    tenant_id: uuid.UUID, thread_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _thread_dict(_call(get_thread, actor_id, tenant_id, thread_id))


@router.patch("/tenants/{tenant_id}/threads/{thread_id}")
def update_thread_route(
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: UpdateThreadRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _thread_dict(_call(update_thread, actor_id, tenant_id, thread_id, channel=body.channel))


@router.delete("/tenants/{tenant_id}/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread_route(
    tenant_id: uuid.UUID, thread_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_thread, actor_id, tenant_id, thread_id)


@router.post("/tenants/{tenant_id}/threads/{thread_id}/assign")
def assign_thread_route(
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: AssignThreadRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _thread_dict(_call(assign_thread, actor_id, tenant_id, thread_id, body.assignee_user_id))


# --- Messages ---------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED
)
def create_message_route(
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: CreateMessageRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _message_dict(
        _call(
            create_message,
            actor_id,
            tenant_id,
            thread_id,
            direction=body.direction,
            is_internal_note=body.is_internal_note,
            body=body.body,
            author_user_id=actor_id,
        )
    )


@router.get("/tenants/{tenant_id}/threads/{thread_id}/messages")
def list_messages_route(
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _message_dict(v)
        for v in _call(list_messages, actor_id, tenant_id, thread_id, limit=limit, offset=offset)
    ]


@router.post("/tenants/{tenant_id}/threads/{thread_id}/send-email")
def send_email_route(
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: SendEmailRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _message_dict(
        _call(
            send_email_message,
            actor_id,
            tenant_id,
            thread_id,
            to_email=body.to_email,
            subject=body.subject,
            body=body.body,
        )
    )


# --- Templates ----------------------------------------------------------


@router.post("/tenants/{tenant_id}/templates", status_code=status.HTTP_201_CREATED)
def create_template_route(
    tenant_id: uuid.UUID,
    body: CreateTemplateRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _template_dict(
        _call(
            create_template,
            actor_id,
            tenant_id,
            name=body.name,
            body=body.body,
            channel=body.channel,
        )
    )


@router.get("/tenants/{tenant_id}/templates")
def list_templates_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [_template_dict(v) for v in _call(list_templates, actor_id, tenant_id)]


@router.get("/tenants/{tenant_id}/templates/{template_id}")
def get_template_route(
    tenant_id: uuid.UUID, template_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _template_dict(_call(get_template, actor_id, tenant_id, template_id))


@router.patch("/tenants/{tenant_id}/templates/{template_id}")
def update_template_route(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    body: UpdateTemplateRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _template_dict(
        _call(
            update_template,
            actor_id,
            tenant_id,
            template_id,
            body=body.body,
            channel=body.channel,
        )
    )


@router.delete(
    "/tenants/{tenant_id}/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_template_route(
    tenant_id: uuid.UUID, template_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_template, actor_id, tenant_id, template_id)
