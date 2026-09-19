"""The Marketing API (docs/ROADMAP.md Phase 6), mounted under
`/v1/marketing` in `product/api/main.py`.

**Ingress dependency choice -- read `docs/ADR/0002-agency-cross-tenant-
route-authorization.md`'s Phase 4 addendum before changing this.** Every
route below uses `api.dependencies.get_current_actor`, not
`api.dependencies.get_tenant_context`/`require_permission()` -- an agency
owner reaching a client's marketing data only via inherited `SUBTREE`
role has no direct membership at that client tenant, so
`get_tenant_context()` would 404 them. Every `product/marketing/*.py`
service function performs its own `core.rbac.can()` check via
`product.marketing.permissions.require()` before touching any
`marketing.*` row -- this is a different, equally-enforced ingress
dependency, not a bypass.

**Non-enumeration**: `MarketingAccessDeniedError` and
`MarketingReferenceNotFoundError` both map to the identical `404` shape
`api.errors.not_found()` uses elsewhere in this platform -- never a
`403`, never a distinguishable message between "doesn't exist" and
"exists but you can't touch it." `MarketingValidationError` and the
`core.email`/`product.marketing.sms` provider-configuration errors that
can surface synchronously from `start_campaign_send()`'s own segment
resolution are client/state input errors, mapped to a plain `400`
instead.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found, rate_limited, service_unavailable
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from infra.ratelimit import (
    RateLimitBackendError,
    RateLimitExceededError,
    enforce_rate_limit,
    get_ratelimit_config,
)
from pydantic import BaseModel, Field

from product.marketing.campaigns import (
    CampaignView,
    cancel_campaign,
    create_campaign,
    delete_campaign,
    get_campaign,
    list_campaigns,
    update_campaign,
)
from product.marketing.errors import (
    MarketingAccessDeniedError,
    MarketingFormTokenInvalidError,
    MarketingReferenceNotFoundError,
    MarketingValidationError,
)
from product.marketing.forms import (
    FormFieldDefinition,
    FormSubmissionView,
    FormView,
    create_form,
    delete_form,
    get_form,
    list_form_submissions,
    list_forms,
    submit_form,
)
from product.marketing.models import (
    MAX_CAMPAIGN_BODY_LENGTH,
    MAX_CAMPAIGN_SUBJECT_LENGTH,
    MAX_CLICK_TARGET_URL_LENGTH,
    MAX_FORM_NAME_LENGTH,
    MAX_TEMPLATE_CONTENT_LENGTH,
    MAX_TEMPLATE_NAME_LENGTH,
)
from product.marketing.pagination import DEFAULT_PAGE_SIZE
from product.marketing.recipients import list_campaign_recipients
from product.marketing.sending import start_campaign_send
from product.marketing.suppressions import (
    SuppressionView,
    create_suppression,
    delete_suppression,
    list_suppressions,
)
from product.marketing.templates import (
    TemplateView,
    clone_template,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from product.marketing.tracking import (
    TRANSPARENT_GIF_BYTES,
    record_click_and_resolve_target,
    record_open,
)

router = APIRouter(prefix="/v1/marketing", tags=["marketing"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    MarketingAccessDeniedError,
    MarketingReferenceNotFoundError,
)
_PUBLIC_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (MarketingFormTokenInvalidError,)
_VALIDATION_ERRORS: tuple[type[Exception], ...] = (MarketingValidationError,)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except _PUBLIC_NOT_FOUND_ERRORS:
        raise not_found("resource") from None


async def _acall(fn, *args, **kwargs):
    """The `async def` counterpart of `_call()` -- used by
    `start_campaign_send()`, the one marketing service function that is
    itself a coroutine (it awaits `infra.jobs.enqueue_job()`), mirroring
    `product/crm/routes.py::_acall()`'s identical role for
    `enqueue_contact_import()`."""
    try:
        return await fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request bodies ---------------------------------------------------------


class CreateCampaignRequest(BaseModel):
    name: str = Field(max_length=255)
    channel: str
    body: str = Field(default="", max_length=MAX_CAMPAIGN_BODY_LENGTH)
    subject: str | None = Field(default=None, max_length=MAX_CAMPAIGN_SUBJECT_LENGTH)
    segment_q: str | None = Field(default=None, max_length=255)
    segment_tag: str | None = Field(default=None, max_length=255)
    segment_custom_field: list[str] = Field(default_factory=list)
    template_id: uuid.UUID | None = None
    click_target_url: str | None = Field(default=None, max_length=MAX_CLICK_TARGET_URL_LENGTH)


class UpdateCampaignRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=MAX_CAMPAIGN_SUBJECT_LENGTH)
    body: str | None = Field(default=None, max_length=MAX_CAMPAIGN_BODY_LENGTH)
    template_id: uuid.UUID | None = None
    click_target_url: str | None = Field(default=None, max_length=MAX_CLICK_TARGET_URL_LENGTH)
    update_click_target_url: bool = False


class CreateSuppressionRequest(BaseModel):
    contact_id: uuid.UUID
    channel: str
    reason: str


class FormFieldDefinitionRequest(BaseModel):
    name: str = Field(max_length=255)
    field_type: str
    required: bool = False


class CreateFormRequest(BaseModel):
    name: str = Field(max_length=MAX_FORM_NAME_LENGTH)
    fields: list[FormFieldDefinitionRequest]


class SubmitFormRequest(BaseModel):
    """`fields` is bounded by `product.marketing.forms.submit_form()`'s
    own validation, not by this model: an unknown field name (one the
    form doesn't declare) is rejected outright, and every declared
    field's value is length-checked -- together these already bound both
    the shape and the size of what a submission can carry, without this
    model needing a separate limit of its own."""

    fields: dict[str, str] = Field(default_factory=dict)


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=MAX_TEMPLATE_NAME_LENGTH)
    template_type: str
    content: str = Field(max_length=MAX_TEMPLATE_CONTENT_LENGTH)


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_TEMPLATE_NAME_LENGTH)
    content: str | None = Field(default=None, max_length=MAX_TEMPLATE_CONTENT_LENGTH)


class CloneTemplateRequest(BaseModel):
    new_name: str = Field(max_length=MAX_TEMPLATE_NAME_LENGTH)


# --- Serialization -----------------------------------------------------------


def _campaign_dict(view: CampaignView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "channel": view.channel,
        "status": view.status,
        "subject": view.subject,
        "body": view.body,
        "segment_query": view.segment_query,
        "template_id": str(view.template_id) if view.template_id else None,
        "click_target_url": view.click_target_url,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _suppression_dict(view: SuppressionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id),
        "channel": view.channel,
        "reason": view.reason,
        "created_at": view.created_at.isoformat(),
    }


def _form_dict(view: FormView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "form_token": view.form_token,
        "fields": [
            {"name": f.name, "field_type": f.field_type, "required": f.required}
            for f in view.field_definitions
        ],
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _form_submission_dict(view: FormSubmissionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "form_id": str(view.form_id),
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "submitted_data": view.submitted_data,
        "created_at": view.created_at.isoformat(),
    }


def _template_dict(view: TemplateView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "template_type": view.template_type,
        "content": view.content,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


# --- Campaigns ----------------------------------------------------------------


@router.post("/tenants/{tenant_id}/campaigns", status_code=status.HTTP_201_CREATED)
def create_campaign_route(
    tenant_id: uuid.UUID,
    body: CreateCampaignRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _campaign_dict(
        _call(
            create_campaign,
            actor_id,
            tenant_id,
            name=body.name,
            channel=body.channel,
            body=body.body,
            subject=body.subject,
            segment_q=body.segment_q,
            segment_tag=body.segment_tag,
            segment_custom_field=body.segment_custom_field or None,
            template_id=body.template_id,
            click_target_url=body.click_target_url,
        )
    )


@router.get("/tenants/{tenant_id}/campaigns")
def list_campaigns_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _campaign_dict(v)
        for v in _call(list_campaigns, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/campaigns/{campaign_id}")
def get_campaign_route(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _campaign_dict(_call(get_campaign, actor_id, tenant_id, campaign_id))


@router.patch("/tenants/{tenant_id}/campaigns/{campaign_id}")
def update_campaign_route(
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    body: UpdateCampaignRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _campaign_dict(
        _call(
            update_campaign,
            actor_id,
            tenant_id,
            campaign_id,
            name=body.name,
            subject=body.subject,
            body=body.body,
            template_id=body.template_id,
            click_target_url=body.click_target_url,
            _update_click_target_url=body.update_click_target_url,
        )
    )


@router.delete(
    "/tenants/{tenant_id}/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_campaign_route(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_campaign, actor_id, tenant_id, campaign_id)


@router.post(
    "/tenants/{tenant_id}/campaigns/{campaign_id}/send", status_code=status.HTTP_202_ACCEPTED
)
async def send_campaign_route(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    result = await _acall(start_campaign_send, actor_id, tenant_id, campaign_id)
    return {
        "campaign_id": str(result.campaign_id),
        "recipient_count": result.recipient_count,
        "suppressed_count": result.suppressed_count,
        "job_id": result.job_id,
    }


@router.post("/tenants/{tenant_id}/campaigns/{campaign_id}/cancel")
def cancel_campaign_route(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _campaign_dict(_call(cancel_campaign, actor_id, tenant_id, campaign_id))


@router.get("/tenants/{tenant_id}/campaigns/{campaign_id}/recipients")
def list_campaign_recipients_route(
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        {
            "id": str(v.id),
            "campaign_id": str(v.campaign_id),
            "contact_id": str(v.contact_id) if v.contact_id else None,
            "status": v.status,
            "sent_at": v.sent_at.isoformat() if v.sent_at else None,
            "error": v.error,
        }
        for v in _call(
            list_campaign_recipients, actor_id, tenant_id, campaign_id, limit=limit, offset=offset
        )
    ]


# --- Suppressions --------------------------------------------------------------


@router.post("/tenants/{tenant_id}/suppressions", status_code=status.HTTP_201_CREATED)
def create_suppression_route(
    tenant_id: uuid.UUID,
    body: CreateSuppressionRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _suppression_dict(
        _call(
            create_suppression,
            actor_id,
            tenant_id,
            contact_id=body.contact_id,
            channel=body.channel,
            reason=body.reason,
        )
    )


@router.get("/tenants/{tenant_id}/suppressions")
def list_suppressions_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _suppression_dict(v)
        for v in _call(list_suppressions, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.delete(
    "/tenants/{tenant_id}/suppressions/{suppression_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_suppression_route(
    tenant_id: uuid.UUID,
    suppression_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_suppression, actor_id, tenant_id, suppression_id)


# --- Forms (authenticated management) -----------------------------------------


@router.post("/tenants/{tenant_id}/forms", status_code=status.HTTP_201_CREATED)
def create_form_route(
    tenant_id: uuid.UUID,
    body: CreateFormRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    fields = [
        FormFieldDefinition(name=f.name, field_type=f.field_type, required=f.required)
        for f in body.fields
    ]
    return _form_dict(_call(create_form, actor_id, tenant_id, name=body.name, fields=fields))


@router.get("/tenants/{tenant_id}/forms")
def list_forms_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _form_dict(v) for v in _call(list_forms, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/forms/{form_id}")
def get_form_route(
    tenant_id: uuid.UUID, form_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _form_dict(_call(get_form, actor_id, tenant_id, form_id))


@router.delete("/tenants/{tenant_id}/forms/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form_route(
    tenant_id: uuid.UUID, form_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_form, actor_id, tenant_id, form_id)


@router.get("/tenants/{tenant_id}/forms/{form_id}/submissions")
def list_form_submissions_route(
    tenant_id: uuid.UUID,
    form_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _form_submission_dict(v)
        for v in _call(
            list_form_submissions, actor_id, tenant_id, form_id, limit=limit, offset=offset
        )
    ]


# --- Forms (public, unauthenticated submission) -------------------------------


async def _enforce_public_rate_limit(key: str) -> None:
    """Mirrors `saas-os`'s own `api/dependencies.py
    ::_enforce_rate_limit_for_route()` fail-closed posture exactly: a
    backend failure rejects the request (never silently allowed, never
    falsely reported as a 429) -- the one difference here is there is no
    `RequestContext`/tenant to scope by yet, so the key is caller-chosen
    (the form token, or the tracking token) rather than `tenant_id:path`."""
    try:
        await enforce_rate_limit(key, config=get_ratelimit_config())
    except RateLimitExceededError as exc:
        raise rate_limited(exc.retry_after_seconds) from None
    except RateLimitBackendError:
        raise service_unavailable(5) from None


@router.post("/forms/{form_token}/submit", status_code=status.HTTP_201_CREATED)
async def submit_form_route(form_token: str, body: SubmitFormRequest) -> dict[str, object]:
    """The one deliberately-unauthenticated write path in this product
    (docs/ROADMAP.md Phase 6.3) -- no `get_current_actor` dependency, no
    `tenant_id` in the path (the token resolves it). Rate-limited by
    `form_token` before anything else runs. An unknown token yields the
    identical non-enumerating 404 shape every other lookup failure in
    this product uses."""
    await _enforce_public_rate_limit(f"marketing_form_submit:{form_token}")
    result = _call(submit_form, form_token, body.fields)
    return {
        "submission_id": str(result.submission_id),
        "contact_id": str(result.contact_id) if result.contact_id else None,
    }


# --- Templates ------------------------------------------------------------------


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
            template_type=body.template_type,
            content=body.content,
        )
    )


@router.get("/tenants/{tenant_id}/templates")
def list_templates_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _template_dict(v)
        for v in _call(list_templates, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/templates/{template_id}")
def get_template_route(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
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
            name=body.name,
            content=body.content,
        )
    )


@router.delete(
    "/tenants/{tenant_id}/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_template_route(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_template, actor_id, tenant_id, template_id)


@router.post("/tenants/{tenant_id}/templates/{template_id}/clone")
def clone_template_route(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    body: CloneTemplateRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _template_dict(
        _call(clone_template, actor_id, tenant_id, template_id, new_name=body.new_name)
    )


# --- Tracking (public, unauthenticated) -----------------------------------------


@router.get("/track/open/{tracking_token}")
def track_open_route(tracking_token: str) -> Response:
    """Never a 404, regardless of whether `tracking_token` resolves --
    see `product/marketing/tracking.py`'s own module docstring for why a
    tracking pixel must fail silently rather than leak a distinguishable
    signal. Not rate-limited (unlike form submission): a legitimate email
    client may fetch this several times in quick succession while
    rendering, and `record_open()` is already idempotent -- a rate limit
    here would risk dropping a real open, for no security benefit (this
    endpoint performs no write an attacker could abuse at any volume
    beyond an ordinary idempotent no-op)."""
    record_open(tracking_token)
    return Response(content=TRANSPARENT_GIF_BYTES, media_type="image/gif")


@router.get("/track/click/{tracking_token}")
def track_click_route(tracking_token: str) -> RedirectResponse:
    """Redirects to the resolved campaign's own server-stored
    `click_target_url` -- and ONLY that; this handler accepts no query
    parameter of any kind, so a caller-supplied `?url=`/`?redirect=`/
    `?next=` has zero effect on the redirect target (see
    `product/marketing/tracking.py::record_click_and_resolve_target()`'s
    own docstring for the full open-redirect-safety reasoning). An
    unknown token redirects to the fixed fallback, never a 404 -- same
    non-enumeration reasoning as the open-tracking route."""
    target = record_click_and_resolve_target(tracking_token)
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
