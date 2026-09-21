"""The Reputation API (docs/ROADMAP.md Phase 12), mounted under
`/v1/reputation` in `product/api/main.py` -- **not yet actually mounted**;
see this module's own package docstring
(`product/reputation/__init__.py`) and this phase's implementation/audit
report for why `product/api/main.py` is out of this phase's scope.

**Ingress dependency choice** -- identical reasoning to
`product/websites/routes.py`'s own module docstring
(`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum): every route below uses `api.dependencies.get_current_actor`,
never `get_tenant_context()`/`require_permission()`. Every
`product/reputation/*.py` service function performs its own
`core.rbac.can()` check via `product.reputation.permissions.require()`
before touching any `reputation.*` row.

**Non-enumeration**: `ReputationAccessDeniedError`,
`ReputationReferenceNotFoundError` both map to the identical `404` shape
`api.errors.not_found()` uses elsewhere in this platform.
`ReputationValidationError`/`ReputationProviderNotConfiguredError` map to
`400`. `ReputationConflictError` -- the service-layer translation of a
real, database-enforced `UNIQUE` constraint violation -- maps to `409`,
with a fixed, generic `detail` string carrying no internal detail,
mirroring `product/websites/routes.py`'s own identical "fixed message,
never the exception's own text" discipline for its own 409 shape.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.reputation.errors import (
    ReputationAccessDeniedError,
    ReputationConflictError,
    ReputationProviderNotConfiguredError,
    ReputationReferenceNotFoundError,
    ReputationValidationError,
)
from product.reputation.models import (
    MAX_AUTHOR_NAME_LENGTH,
    MAX_RESPONSE_BODY_LENGTH,
    MAX_REVIEW_BODY_LENGTH,
    PROVIDER_MANUAL,
    REQUEST_CHANNEL_EMAIL,
)
from product.reputation.responses import ReviewResponseView, create_response, list_responses
from product.reputation.review_requests import (
    ReviewRequestView,
    cancel_review_request,
    create_review_request,
    get_review_request,
    list_review_requests,
)
from product.reputation.reviews import ReviewView, get_review, list_reviews, record_review

router = APIRouter(prefix="/v1/reputation", tags=["reputation"])

_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    ReputationValidationError,
    ReputationProviderNotConfiguredError,
)
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    ReputationAccessDeniedError,
    ReputationReferenceNotFoundError,
)
_CONFLICT_ERRORS: tuple[type[Exception], ...] = (ReputationConflictError,)


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="That review request/review is already linked or in use.",
    )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _CONFLICT_ERRORS:
        raise _conflict() from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request bodies ----------------------------------------------------------


class CreateReviewRequestRequest(BaseModel):
    contact_id: uuid.UUID
    channel: str = Field(default=REQUEST_CHANNEL_EMAIL, max_length=16)
    message: str | None = Field(default=None, max_length=4000)


class RecordReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    author_name: str = Field(max_length=MAX_AUTHOR_NAME_LENGTH)
    body: str | None = Field(default=None, max_length=MAX_REVIEW_BODY_LENGTH)
    provider: str = Field(default=PROVIDER_MANUAL, max_length=32)
    review_request_id: uuid.UUID | None = None


class CreateReviewResponseRequest(BaseModel):
    body: str = Field(max_length=MAX_RESPONSE_BODY_LENGTH)


# --- Serialization -------------------------------------------------------------


def _review_request_dict(view: ReviewRequestView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id),
        "channel": view.channel,
        "status": view.status,
        "failure_reason": view.failure_reason,
        "requested_by_user_id": str(view.requested_by_user_id),
        "sent_at": view.sent_at.isoformat() if view.sent_at else None,
        "cancelled_at": view.cancelled_at.isoformat() if view.cancelled_at else None,
        "fulfilled_at": view.fulfilled_at.isoformat() if view.fulfilled_at else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _review_dict(view: ReviewView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "review_request_id": str(view.review_request_id) if view.review_request_id else None,
        "provider": view.provider,
        "external_review_id": view.external_review_id,
        "rating": view.rating,
        "author_name": view.author_name,
        "body": view.body,
        "status": view.status,
        "received_at": view.received_at.isoformat(),
        "recorded_by_user_id": str(view.recorded_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _response_dict(view: ReviewResponseView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "review_id": str(view.review_id),
        "body": view.body,
        "posted_by_user_id": str(view.posted_by_user_id),
        "created_at": view.created_at.isoformat(),
    }


# --- Review requests -----------------------------------------------------------


@router.post("/tenants/{tenant_id}/review-requests", status_code=status.HTTP_201_CREATED)
def create_review_request_route(
    tenant_id: uuid.UUID,
    body: CreateReviewRequestRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _review_request_dict(
        _call(
            create_review_request,
            actor_id,
            tenant_id,
            body.contact_id,
            channel=body.channel,
            message=body.message,
        )
    )


@router.get("/tenants/{tenant_id}/review-requests")
def list_review_requests_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _review_request_dict(v)
        for v in _call(
            list_review_requests,
            actor_id,
            tenant_id,
            contact_id=contact_id,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/tenants/{tenant_id}/review-requests/{request_id}")
def get_review_request_route(
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _review_request_dict(_call(get_review_request, actor_id, tenant_id, request_id))


@router.post("/tenants/{tenant_id}/review-requests/{request_id}/cancel")
def cancel_review_request_route(
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _review_request_dict(_call(cancel_review_request, actor_id, tenant_id, request_id))


# --- Reviews ---------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/reviews", status_code=status.HTTP_201_CREATED)
def record_review_route(
    tenant_id: uuid.UUID,
    body: RecordReviewRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _review_dict(
        _call(
            record_review,
            actor_id,
            tenant_id,
            rating=body.rating,
            author_name=body.author_name,
            body=body.body,
            provider=body.provider,
            review_request_id=body.review_request_id,
        )
    )


@router.get("/tenants/{tenant_id}/reviews")
def list_reviews_route(
    tenant_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _review_dict(v)
        for v in _call(list_reviews, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/reviews/{review_id}")
def get_review_route(
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _review_dict(_call(get_review, actor_id, tenant_id, review_id))


# --- Review responses ------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/reviews/{review_id}/responses", status_code=status.HTTP_201_CREATED
)
def create_response_route(
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    body: CreateReviewResponseRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _response_dict(_call(create_response, actor_id, tenant_id, review_id, body=body.body))


@router.get("/tenants/{tenant_id}/reviews/{review_id}/responses")
def list_responses_route(
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _response_dict(v)
        for v in _call(list_responses, actor_id, tenant_id, review_id, limit=limit, offset=offset)
    ]


__all__ = ["router"]
