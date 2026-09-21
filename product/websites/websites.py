"""Website CRUD (docs/ROADMAP.md Phase 11.1).

Every mutating/read function authorizes via
`product.websites.permissions.require()` first, then the actual database
access, then `core.audit_log.record()` for mutations -- metadata carries
only identifiers, never a website's own `name` (mirrors
`product/appointments/calendars.py`'s own "bounded/identifier-only
metadata is this product's uniform discipline" precedent).

**`Website` is read/written through a plain, untenanted
`infra.db.session_scope()` with an explicit `tenant_id` filter, never
`tenant_session_scope()`** -- `websites.websites` deliberately carries no
RLS policy (`product/websites/models.py::Website`'s own module
docstring); this mirrors `product/appointments/calendars.py
::get_or_create_booking_link()`'s/`product/telephony/purge.py
::TelephonyUnscopedDataPurgeParticipant`'s identical shape for their own
unscoped tables. `resolve_website_by_slug()` is the one function with no
`actor_user_id`/authorization at all -- it is the public, untenanted
lookup a published-page read resolves through *before* any tenant
context exists, exactly `product/appointments/booking.py
::resolve_booking_link()`'s own shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, session_scope

from product.websites.errors import (
    WebsiteReferenceNotFoundError,
    WebsiteSlugTakenError,
    WebsiteValidationError,
)
from product.websites.models import MAX_CUSTOM_DOMAIN_LENGTH, MAX_WEBSITE_NAME_LENGTH, Website
from product.websites.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.websites.permissions import WEBSITE_RESOURCE, require
from product.websites.slugs import normalize_slug


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise WebsiteValidationError("name must not be empty.")
    if len(name) > MAX_WEBSITE_NAME_LENGTH:
        raise WebsiteValidationError(f"name exceeds {MAX_WEBSITE_NAME_LENGTH} characters.")
    return name


def _validate_custom_domain(custom_domain: str | None) -> str | None:
    if custom_domain is None:
        return None
    if not isinstance(custom_domain, str) or not custom_domain.strip():
        raise WebsiteValidationError("custom_domain must not be empty when provided.")
    if len(custom_domain) > MAX_CUSTOM_DOMAIN_LENGTH:
        raise WebsiteValidationError(
            f"custom_domain exceeds {MAX_CUSTOM_DOMAIN_LENGTH} characters."
        )
    return custom_domain.lower()


@dataclass(frozen=True, slots=True)
class WebsiteView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    custom_domain: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _to_view(row: Website) -> WebsiteView:
    return WebsiteView(
        id=row.id,
        tenant_id=row.tenant_id,
        slug=row.slug,
        name=row.name,
        custom_domain=row.custom_domain,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_website(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    slug: str,
    name: str,
    custom_domain: str | None = None,
) -> WebsiteView:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="create")
    normalized_slug = normalize_slug(slug)
    validated_name = _validate_name(name)
    validated_domain = _validate_custom_domain(custom_domain)

    website_id = uuid.uuid4()
    try:
        with session_scope() as session:
            session.add(
                Website(
                    id=website_id,
                    tenant_id=tenant_id,
                    slug=normalized_slug,
                    name=validated_name,
                    custom_domain=validated_domain,
                    created_by_user_id=actor_user_id,
                )
            )
            session.flush()
    except IntegrityError as exc:
        field = "custom_domain" if validated_domain is not None else "slug"
        value = validated_domain if validated_domain is not None else normalized_slug
        raise WebsiteSlugTakenError(field, value) from exc

    with session_scope() as session:
        row = session.get(Website, website_id)
        assert row is not None
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.website.created",
        resource_type="websites.website",
        resource_id=str(website_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, website_id: uuid.UUID) -> Website:
    row = session.get(Website, website_id)
    if row is None or row.tenant_id != tenant_id:
        raise WebsiteReferenceNotFoundError("website", website_id)
    return row


def get_website(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, website_id: uuid.UUID
) -> WebsiteView:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="read")
    with session_scope() as session:
        row = _get_owned_row(session, tenant_id, website_id)
        session.expunge(row)
    return _to_view(row)


def list_websites(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[WebsiteView]:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with session_scope() as session:
        rows = (
            session.execute(
                select(Website)
                .where(Website.tenant_id == tenant_id)
                .order_by(Website.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_website(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    *,
    name: str | None = None,
    custom_domain: str | None = ...,  # type: ignore[assignment] -- sentinel: omitted vs. explicit None
) -> WebsiteView:
    """`custom_domain` uses `...` (Ellipsis) as its own "omitted" sentinel
    -- `None` is itself a meaningful, valid value here (clear the custom
    domain), so it cannot double as "caller didn't pass this field."""
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="update")
    validated_name = _validate_name(name) if name is not None else None
    validated_domain = _validate_custom_domain(custom_domain) if custom_domain is not ... else ...

    try:
        with session_scope() as session:
            row = _get_owned_row(session, tenant_id, website_id)
            if validated_name is not None:
                row.name = validated_name
            if validated_domain is not ...:
                row.custom_domain = validated_domain
            session.flush()
            session.refresh(row)
            session.expunge(row)
    except IntegrityError as exc:
        raise WebsiteSlugTakenError("custom_domain", str(custom_domain)) from exc
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.website.updated",
        resource_type="websites.website",
        resource_id=str(website_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_website(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, website_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="delete")
    with session_scope() as session:
        row = _get_owned_row(session, tenant_id, website_id)
        session.delete(row)
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.website.deleted",
        resource_type="websites.website",
        resource_id=str(website_id),
        outcome=AuditOutcome.SUCCESS,
    )


def resolve_website_by_slug(slug: str) -> WebsiteView | None:
    """The public, untenanted lookup a published-page read resolves
    through -- no `actor_user_id`, no authorization check, mirrors
    `product/appointments/booking.py::resolve_booking_link()` exactly.
    Returns `None` (never raises) for an unknown or malformed slug, so a
    caller can produce a non-enumerating 404."""
    try:
        normalized = normalize_slug(slug)
    except WebsiteValidationError:
        return None
    with session_scope() as session:
        row = session.execute(
            select(Website).where(Website.slug == normalized)
        ).scalar_one_or_none()
        if row is None:
            return None
        session.expunge(row)
    return _to_view(row)


__all__ = [
    "WebsiteView",
    "create_website",
    "delete_website",
    "get_website",
    "list_websites",
    "resolve_website_by_slug",
    "update_website",
]
