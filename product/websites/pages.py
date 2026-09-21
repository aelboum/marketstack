"""Page CRUD and draft/publish lifecycle (docs/ROADMAP.md Phase 11.1).

Every mutating/read function authorizes via
`product.websites.permissions.require()` first (the same
`WEBSITE_RESOURCE` a `Website` mutation uses -- a page has no independent
access boundary apart from the website that owns it,
`product/websites/permissions.py`'s own module docstring), then the
actual `tenant_session_scope()` read/write (ordinary RLS-scoped, unlike
`Website` itself), then `core.audit_log.record()` for mutations.

**Lifecycle: exactly two states, `draft`/`published`** — no "archived,"
no "scheduled," no "pending review." A brand-new page starts `draft`;
`publish_page()` copies `content_blocks` into `published_content_blocks`
and moves to `published`; `unpublish_page()` moves back to `draft`
without discarding `published_content_blocks` (a subsequent publish
overwrites it; nothing reads a stale snapshot in between, since
`get_published_page()` below also checks `status == published` before
returning anything). Editing a page's draft content
(`update_page()`) never touches `published_content_blocks` -- a
published page's public content only ever changes on an explicit
`publish_page()` call, never as a side effect of an in-progress edit.

**`get_published_page()` is the one function with no
`actor_user_id`/authorization at all** — the public, tenant-scoped read
a caller reaches only after already resolving a `Website` via
`product.websites.websites.resolve_website_by_slug()` (which supplies
the `tenant_id` this function uses to scope its own
`tenant_session_scope()` read). It reads `published_content_blocks`
exclusively and only for a row whose `status == published` -- a draft
edit, or an unpublished page, is structurally unreachable through this
path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, session_scope, tenant_session_scope

from product.websites.content_blocks import validate_content_blocks
from product.websites.errors import (
    WebsiteReferenceNotFoundError,
    WebsiteSlugTakenError,
    WebsiteValidationError,
)
from product.websites.models import (
    MAX_PAGE_TITLE_LENGTH,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    Page,
    Website,
)
from product.websites.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.websites.permissions import WEBSITE_RESOURCE, require
from product.websites.slugs import normalize_slug


def _validate_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise WebsiteValidationError("title must not be empty.")
    if len(title) > MAX_PAGE_TITLE_LENGTH:
        raise WebsiteValidationError(f"title exceeds {MAX_PAGE_TITLE_LENGTH} characters.")
    return title


def _require_website_in_tenant(tenant_id: uuid.UUID, website_id: uuid.UUID) -> None:
    """Pre-validates the parent `Website` exists in this tenant before a
    `Page` insert is attempted -- mirrors `product/telephony/numbers.py
    ::_require_phone_number_in_tenant()`'s identical precedent. Without
    this, an unknown/cross-tenant `website_id` would surface only as the
    composite FK's own `IntegrityError`, which `create_page()`'s
    `except IntegrityError` clause would otherwise mislabel as
    `WebsiteSlugTakenError` (409) instead of the correct
    `WebsiteReferenceNotFoundError` (404) -- `Website` is unscoped
    (`product/websites/models.py`'s own docstring), so this check uses a
    plain `session_scope()` with an explicit `tenant_id` filter, the same
    discipline every other unscoped-table read in this module uses."""
    with session_scope() as session:
        row = session.get(Website, website_id)
        if row is None or row.tenant_id != tenant_id:
            raise WebsiteReferenceNotFoundError("website", website_id)


@dataclass(frozen=True, slots=True)
class PageView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    website_id: uuid.UUID
    slug: str
    title: str
    status: str
    content_blocks: list
    published_content_blocks: list | None
    published_at: datetime | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PublishedPageView:
    """Deliberately narrower than `PageView` -- only what a public reader
    may ever see: no `created_by_user_id`, no draft `content_blocks`, no
    internal `id`/`website_id` (the slug pair is the only identifier a
    public caller supplied)."""

    tenant_id: uuid.UUID
    website_id: uuid.UUID
    page_id: uuid.UUID
    title: str
    content_blocks: list
    published_at: datetime


def _to_view(row: Page) -> PageView:
    return PageView(
        id=row.id,
        tenant_id=row.tenant_id,
        website_id=row.website_id,
        slug=row.slug,
        title=row.title,
        status=row.status,
        content_blocks=row.content_blocks,
        published_content_blocks=row.published_content_blocks,
        published_at=row.published_at,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_page(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    *,
    slug: str,
    title: str,
    content_blocks: list | None = None,
) -> PageView:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="create")
    _require_website_in_tenant(tenant_id, website_id)
    normalized_slug = normalize_slug(slug)
    validated_title = _validate_title(title)
    blocks = content_blocks if content_blocks is not None else []
    validate_content_blocks(blocks)

    page_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            session.add(
                Page(
                    id=page_id,
                    tenant_id=tenant_id,
                    website_id=website_id,
                    slug=normalized_slug,
                    title=validated_title,
                    status=STATUS_DRAFT,
                    content_blocks=blocks,
                    created_by_user_id=actor_user_id,
                )
            )
            session.flush()
    except IntegrityError as exc:
        raise WebsiteSlugTakenError("slug", normalized_slug) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Page, page_id)
        assert row is not None
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.page.created",
        resource_type="websites.page",
        resource_id=str(page_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"website_id": str(website_id)},
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, page_id: uuid.UUID) -> Page:
    row = session.get(Page, page_id)
    if row is None or row.tenant_id != tenant_id:
        raise WebsiteReferenceNotFoundError("page", page_id)
    return row


def get_page(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, page_id: uuid.UUID) -> PageView:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, page_id)
        session.expunge(row)
    return _to_view(row)


def list_pages(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[PageView]:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Page)
                .where(Page.tenant_id == tenant_id, Page.website_id == website_id)
                .order_by(Page.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_page(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    *,
    title: str | None = None,
    content_blocks: list | None = None,
) -> PageView:
    """Only ever touches draft state (`title`, `content_blocks`) -- never
    `published_content_blocks`/`published_at`, which only
    `publish_page()` writes. Editing a published page's draft does not
    change what is publicly visible until the next explicit publish."""
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="update")
    validated_title = _validate_title(title) if title is not None else None
    if content_blocks is not None:
        validate_content_blocks(content_blocks)

    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, page_id)
        if validated_title is not None:
            row.title = validated_title
        if content_blocks is not None:
            row.content_blocks = content_blocks
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.page.updated",
        resource_type="websites.page",
        resource_id=str(page_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_page(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, page_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, page_id)
        session.delete(row)
        session.flush()
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.page.deleted",
        resource_type="websites.page",
        resource_id=str(page_id),
        outcome=AuditOutcome.SUCCESS,
    )


def publish_page(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, page_id: uuid.UUID) -> PageView:
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, page_id)
        row.published_content_blocks = row.content_blocks
        row.status = STATUS_PUBLISHED
        row.published_at = datetime.now(UTC)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.page.published",
        resource_type="websites.page",
        resource_id=str(page_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def unpublish_page(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, page_id: uuid.UUID) -> PageView:
    """Moves a page back to `draft`. Does NOT clear
    `published_content_blocks` -- only `status` (checked by
    `get_published_page()`) controls public visibility; the last
    snapshot is kept so a follow-up `publish_page()` is not required to
    reconstruct it, and so an operator can see what was last live."""
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, page_id)
        row.status = STATUS_DRAFT
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="websites.page.unpublished",
        resource_type="websites.page",
        resource_id=str(page_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_published_page(
    tenant_id: uuid.UUID, website_id: uuid.UUID, page_slug: str
) -> PublishedPageView | None:
    """The public read. No authorization, no draft content, no page
    reachable unless `status == published` -- returns `None` (never
    raises) for anything else, so a caller produces a non-enumerating
    404 exactly like `product.websites.websites.resolve_website_by_slug()`
    already does for an unknown website slug."""
    try:
        normalized_slug = normalize_slug(page_slug)
    except WebsiteValidationError:
        return None
    with tenant_session_scope(tenant_id) as session:
        row = session.execute(
            select(Page).where(
                Page.tenant_id == tenant_id,
                Page.website_id == website_id,
                Page.slug == normalized_slug,
                Page.status == STATUS_PUBLISHED,
            )
        ).scalar_one_or_none()
        if row is None or row.published_content_blocks is None or row.published_at is None:
            return None
        view = PublishedPageView(
            tenant_id=row.tenant_id,
            website_id=row.website_id,
            page_id=row.id,
            title=row.title,
            content_blocks=row.published_content_blocks,
            published_at=row.published_at,
        )
    return view


__all__ = [
    "PageView",
    "PublishedPageView",
    "create_page",
    "delete_page",
    "get_page",
    "get_published_page",
    "list_pages",
    "publish_page",
    "unpublish_page",
    "update_page",
]
