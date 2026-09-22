"""The Websites API (docs/ROADMAP.md Phase 11.1), mounted under
`/v1/websites` in `product/api/main.py`.

**Ingress dependency choice** -- identical reasoning to
`product/appointments/routes.py`'s own module docstring
(`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum): every authenticated route below uses
`api.dependencies.get_current_actor`, never `get_tenant_context()`/
`require_permission()`. Every `product/websites/*.py` service function
performs its own `core.rbac.can()` check via
`product.websites.permissions.require()` before touching any
`websites.*` row.

**Non-enumeration**: `WebsiteAccessDeniedError`,
`WebsiteReferenceNotFoundError` all map to the identical `404` shape
`api.errors.not_found()` uses elsewhere in this platform.
`WebsiteValidationError` maps to `400`. `WebsiteSlugTakenError` -- the
service-layer translation of the real, database-enforced `UNIQUE`
constraint violation -- maps to a `409`, with a fixed, generic `detail`
string carrying no internal detail, mirroring
`product/appointments/routes.py`'s own identical "fixed message, never
the exception's own text" discipline for its own 409 shape.

**The public page-render route is rate-limited and non-enumerating** --
mirrors `product/appointments/routes.py::public_book_appointment_route()`/
`_enforce_public_rate_limit()` exactly, keyed by the caller-supplied
website/page slug pair (there is no tenant context yet to key by).
Published pages are public by design (docs/ROADMAP.md Phase 11.1's own
security consideration), so this route needs no authentication -- what it
must not become is an unbounded, unrated surface.

**Phase 22 adds a second public, rate-limited route** --
`public_capture_lead_route()`, the identical shape as the page-render
route above, plus a real CRM write via `product/websites/leads.py
::capture_lead()` (`docs/ADR/0015-websites-depends-on-crm.md`, the one
`websites -> crm` edge this module's imports below now include). This is
now the third legitimately-anonymous write path in this product
(`product/marketing/forms.py::submit_form()`,
`product/appointments/booking.py::book_appointment()`'s public path, and
this one) -- reviewed with the same scrutiny each prior one received, not
a precedent for a fourth without equal review.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found, rate_limited, service_unavailable
from core.idempotency import IdempotencyKeyInvalidError
from fastapi import APIRouter, Depends, HTTPException, status
from infra.ratelimit import (
    RateLimitBackendError,
    RateLimitExceededError,
    enforce_rate_limit,
    get_ratelimit_config,
)
from pydantic import BaseModel, Field

from product.websites.errors import (
    WebsiteAccessDeniedError,
    WebsiteReferenceNotFoundError,
    WebsiteSlugTakenError,
    WebsiteValidationError,
)
from product.websites.leads import (
    LeadSubmissionView,
    capture_lead,
    list_lead_submissions,
)
from product.websites.models import (
    MAX_CUSTOM_DOMAIN_LENGTH,
    MAX_LEAD_EMAIL_LENGTH,
    MAX_LEAD_MESSAGE_LENGTH,
    MAX_LEAD_NAME_LENGTH,
    MAX_LEAD_PHONE_LENGTH,
    MAX_PAGE_TITLE_LENGTH,
    MAX_WEBSITE_NAME_LENGTH,
)
from product.websites.pages import (
    PageView,
    create_page,
    delete_page,
    get_page,
    get_published_page,
    list_pages,
    publish_page,
    unpublish_page,
    update_page,
)
from product.websites.slugs import MAX_SLUG_LENGTH
from product.websites.websites import (
    WebsiteView,
    create_website,
    delete_website,
    get_website,
    list_websites,
    resolve_website_by_slug,
    update_website,
)
from product.white_label.branding import DbBrandingProvider

router = APIRouter(prefix="/v1/websites", tags=["websites"])

_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    WebsiteValidationError,
    IdempotencyKeyInvalidError,
)
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    WebsiteAccessDeniedError,
    WebsiteReferenceNotFoundError,
)
_SLUG_TAKEN_ERRORS: tuple[type[Exception], ...] = (WebsiteSlugTakenError,)


def _slug_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="That slug or domain is already in use.",
    )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _SLUG_TAKEN_ERRORS:
        raise _slug_taken() from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


async def _enforce_public_rate_limit(key: str) -> None:
    """Mirrors `product/appointments/routes.py::_enforce_public_rate_limit()`
    exactly -- fail-closed, keyed by the caller-chosen public slug rather
    than a tenant (there is no tenant context yet)."""
    try:
        await enforce_rate_limit(key, config=get_ratelimit_config())
    except RateLimitExceededError as exc:
        raise rate_limited(exc.retry_after_seconds) from None
    except RateLimitBackendError:
        raise service_unavailable(5) from None


# --- Request bodies ----------------------------------------------------------


class CreateWebsiteRequest(BaseModel):
    slug: str = Field(max_length=MAX_SLUG_LENGTH)
    name: str = Field(max_length=MAX_WEBSITE_NAME_LENGTH)
    custom_domain: str | None = Field(default=None, max_length=MAX_CUSTOM_DOMAIN_LENGTH)


class UpdateWebsiteRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_WEBSITE_NAME_LENGTH)
    custom_domain: str | None = Field(default=None, max_length=MAX_CUSTOM_DOMAIN_LENGTH)
    clear_custom_domain: bool = False


class CreatePageRequest(BaseModel):
    slug: str = Field(max_length=MAX_SLUG_LENGTH)
    title: str = Field(max_length=MAX_PAGE_TITLE_LENGTH)
    content_blocks: list = Field(default_factory=list)


class UpdatePageRequest(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_PAGE_TITLE_LENGTH)
    content_blocks: list | None = None


class CaptureLeadRequest(BaseModel):
    first_name: str = Field(max_length=MAX_LEAD_NAME_LENGTH)
    last_name: str = Field(max_length=MAX_LEAD_NAME_LENGTH)
    email: str = Field(max_length=MAX_LEAD_EMAIL_LENGTH)
    phone: str | None = Field(default=None, max_length=MAX_LEAD_PHONE_LENGTH)
    message: str | None = Field(default=None, max_length=MAX_LEAD_MESSAGE_LENGTH)
    idempotency_key: str = Field(min_length=1, max_length=200)


# --- Serialization -------------------------------------------------------------


def _website_dict(view: WebsiteView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "slug": view.slug,
        "name": view.name,
        "custom_domain": view.custom_domain,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _page_dict(view: PageView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "website_id": str(view.website_id),
        "slug": view.slug,
        "title": view.title,
        "status": view.status,
        "content_blocks": view.content_blocks,
        "published_at": view.published_at.isoformat() if view.published_at else None,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _lead_submission_dict(view: LeadSubmissionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "website_id": str(view.website_id),
        "page_id": str(view.page_id),
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "first_name": view.first_name,
        "last_name": view.last_name,
        "email": view.email,
        "phone": view.phone,
        "message": view.message,
        "created_at": view.created_at.isoformat(),
    }


# --- Websites (authenticated) ---------------------------------------------------


@router.post("/tenants/{tenant_id}/websites", status_code=status.HTTP_201_CREATED)
def create_website_route(
    tenant_id: uuid.UUID,
    body: CreateWebsiteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _website_dict(
        _call(
            create_website,
            actor_id,
            tenant_id,
            slug=body.slug,
            name=body.name,
            custom_domain=body.custom_domain,
        )
    )


@router.get("/tenants/{tenant_id}/websites")
def list_websites_route(
    tenant_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _website_dict(v)
        for v in _call(list_websites, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/websites/{website_id}")
def get_website_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _website_dict(_call(get_website, actor_id, tenant_id, website_id))


@router.patch("/tenants/{tenant_id}/websites/{website_id}")
def update_website_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    body: UpdateWebsiteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    # `clear_custom_domain` disambiguates "omitted" from "explicit null" at
    # the HTTP layer (a JSON body cannot otherwise distinguish "field not
    # sent" from "field sent as null" the way `update_website()`'s own
    # `...`-sentinel does) -- translated into that sentinel here, once.
    if body.clear_custom_domain:
        return _website_dict(
            _call(
                update_website, actor_id, tenant_id, website_id, name=body.name, custom_domain=None
            )
        )
    if body.custom_domain is not None:
        return _website_dict(
            _call(
                update_website,
                actor_id,
                tenant_id,
                website_id,
                name=body.name,
                custom_domain=body.custom_domain,
            )
        )
    return _website_dict(_call(update_website, actor_id, tenant_id, website_id, name=body.name))


@router.delete("/tenants/{tenant_id}/websites/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_website_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_website, actor_id, tenant_id, website_id)


# --- Pages (authenticated) ------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/websites/{website_id}/pages", status_code=status.HTTP_201_CREATED
)
def create_page_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    body: CreatePageRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _page_dict(
        _call(
            create_page,
            actor_id,
            tenant_id,
            website_id,
            slug=body.slug,
            title=body.title,
            content_blocks=body.content_blocks,
        )
    )


@router.get("/tenants/{tenant_id}/websites/{website_id}/pages")
def list_pages_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _page_dict(v)
        for v in _call(list_pages, actor_id, tenant_id, website_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/pages/{page_id}")
def get_page_route(
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _page_dict(_call(get_page, actor_id, tenant_id, page_id))


@router.patch("/tenants/{tenant_id}/pages/{page_id}")
def update_page_route(
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    body: UpdatePageRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _page_dict(
        _call(
            update_page,
            actor_id,
            tenant_id,
            page_id,
            title=body.title,
            content_blocks=body.content_blocks,
        )
    )


@router.delete("/tenants/{tenant_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page_route(
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_page, actor_id, tenant_id, page_id)


@router.post("/tenants/{tenant_id}/pages/{page_id}/publish")
def publish_page_route(
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _page_dict(_call(publish_page, actor_id, tenant_id, page_id))


@router.post("/tenants/{tenant_id}/pages/{page_id}/unpublish")
def unpublish_page_route(
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _page_dict(_call(unpublish_page, actor_id, tenant_id, page_id))


# --- Lead submissions (authenticated, staff-facing read) --------------------


@router.get("/tenants/{tenant_id}/websites/{website_id}/leads")
def list_lead_submissions_route(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _lead_submission_dict(v)
        for v in _call(
            list_lead_submissions, actor_id, tenant_id, website_id, limit=limit, offset=offset
        )
    ]


# --- Public, unauthenticated page render -----------------------------------------


@router.get("/public/{website_slug}/{page_slug}")
async def public_get_page_route(website_slug: str, page_slug: str) -> dict[str, object]:
    """The public page-render endpoint (docs/ROADMAP.md Phase 11.1) -- no
    `get_current_actor` dependency, no `tenant_id` in the path
    (`website_slug` resolves it, see `product/websites/websites.py
    ::resolve_website_by_slug()`). Rate-limited by the slug pair before
    anything else runs. Returns the page's bounded content blocks plus
    the tenant's own resolved branding
    (`product/white_label/branding.py::DbBrandingProvider`,
    docs/ROADMAP.md Phase 11.1's own "rendered correctly under the
    tenant's own branding" acceptance criterion) -- never draft content,
    never anything beyond what `get_published_page()` itself already
    bounds."""
    await _enforce_public_rate_limit(f"websites_public:{website_slug}/{page_slug}")

    website = resolve_website_by_slug(website_slug)
    if website is None:
        raise not_found("resource")

    page = get_published_page(website.tenant_id, website.id, page_slug)
    if page is None:
        raise not_found("resource")

    branding = DbBrandingProvider().get_branding(website.tenant_id)

    return {
        "title": page.title,
        "content_blocks": page.content_blocks,
        "published_at": page.published_at.isoformat(),
        "branding": {
            "display_name": branding.display_name,
            "logo_asset_ref": branding.logo_asset_ref,
            "favicon_asset_ref": branding.favicon_asset_ref,
            "color_primary": branding.color_primary,
            "color_secondary": branding.color_secondary,
            "color_accent": branding.color_accent,
            "typography": branding.typography,
        },
    }


@router.post("/public/{website_slug}/{page_slug}/leads", status_code=status.HTTP_201_CREATED)
async def public_capture_lead_route(
    website_slug: str, page_slug: str, body: CaptureLeadRequest
) -> dict[str, object]:
    """The public lead-capture endpoint (docs/ROADMAP.md Phase 22) --
    mirrors `public_get_page_route()`'s own shape exactly: no
    `get_current_actor` dependency, rate-limited by the slug pair before
    anything else runs, non-enumerating 404 for an unknown website/page or
    one that exists but is not published (`capture_lead()` itself treats
    "unpublished" identically to "does not exist," never distinguishing
    the two to an anonymous caller). Returns no internal identifier --
    an anonymous visitor gets only a bare acknowledgement, never a
    `contact_id`/`submission_id` it has no legitimate use for."""
    await _enforce_public_rate_limit(f"websites_public_leads:{website_slug}/{page_slug}")

    website = resolve_website_by_slug(website_slug)
    if website is None:
        raise not_found("resource")

    page = get_published_page(website.tenant_id, website.id, page_slug)
    if page is None:
        raise not_found("resource")

    _call(
        capture_lead,
        website.tenant_id,
        website.id,
        page.page_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        message=body.message,
        idempotency_key=body.idempotency_key,
    )
    return {"status": "received"}


__all__ = ["router"]
