"""`product/websites/pages.py`: Page CRUD, draft/publish lifecycle, the
draft/published content split, RLS-backed tenant isolation, and
authorization (docs/ROADMAP.md Phase 11.1). Real disposable Postgres.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from infra.db import select, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.websites.errors import (
    WebsiteAccessDeniedError,
    WebsiteReferenceNotFoundError,
    WebsiteSlugTakenError,
    WebsiteValidationError,
)
from product.websites.models import STATUS_DRAFT, STATUS_PUBLISHED, Page
from product.websites.pages import (
    create_page,
    delete_page,
    get_page,
    get_published_page,
    list_pages,
    publish_page,
    unpublish_page,
    update_page,
)
from product.websites.websites import create_website

from tests.websites._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _site(owner_id, tenant_id):
    return create_website(owner_id, tenant_id, slug=_name("site"), name="Site")


# --- CRUD, valid creation ----------------------------------------------------


def test_create_get_list_update_delete_page() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")
        assert page.status == STATUS_DRAFT
        assert page.content_blocks == []
        assert page.published_content_blocks is None

        fetched = get_page(owner.id, client.tenant_id, page.id)
        assert fetched.id == page.id

        listed = list_pages(owner.id, client.tenant_id, site.id)
        assert any(p.id == page.id for p in listed)

        updated = update_page(owner.id, client.tenant_id, page.id, title="Renamed Home")
        assert updated.title == "Renamed Home"

        delete_page(owner.id, client.tenant_id, page.id)
        with pytest.raises(WebsiteReferenceNotFoundError):
            get_page(owner.id, client.tenant_id, page.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_page_with_content_blocks() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        blocks = [{"type": "heading", "text": "Welcome", "level": 1}]
        page = create_page(
            owner.id,
            client.tenant_id,
            site.id,
            slug=_name("home"),
            title="Home",
            content_blocks=blocks,
        )
        assert page.content_blocks == blocks
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input ------------------------------------------------------------


def test_create_page_rejects_empty_title() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        with pytest.raises(WebsiteValidationError):
            create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title=" ")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_page_rejects_invalid_content_blocks() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        with pytest.raises(WebsiteValidationError):
            create_page(
                owner.id,
                client.tenant_id,
                site.id,
                slug=_name("home"),
                title="Home",
                content_blocks=[{"type": "button", "text": "Go", "url": "javascript:alert(1)"}],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_update_page_rejects_invalid_content_blocks() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")
        with pytest.raises(WebsiteValidationError):
            update_page(
                owner.id,
                client.tenant_id,
                page.id,
                content_blocks=[{"type": "not-a-real-type"}],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Uniqueness: within-website, not global ----------------------------------


def test_page_slug_unique_within_website() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        shared_slug = _name("dup")
        create_page(owner.id, client.tenant_id, site.id, slug=shared_slug, title="First")
        with pytest.raises(WebsiteSlugTakenError):
            create_page(owner.id, client.tenant_id, site.id, slug=shared_slug, title="Second")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_page_slug_may_repeat_across_different_websites() -> None:
    """Unlike `Website.slug` (globally unique), `Page.slug` is unique only
    within its own website -- two different websites may reuse the
    identical page slug (`product/websites/models.py::Page`'s own
    docstring)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site_a = _site(owner.id, client.tenant_id)
        site_b = _site(owner.id, client.tenant_id)
        shared_slug = _name("home")
        page_a = create_page(owner.id, client.tenant_id, site_a.id, slug=shared_slug, title="A")
        page_b = create_page(owner.id, client.tenant_id, site_b.id, slug=shared_slug, title="B")
        assert page_a.slug == page_b.slug
        assert page_a.website_id != page_b.website_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_page_for_unknown_website_rejected() -> None:
    """`create_page()` pre-validates the parent `Website` exists in this
    tenant (`_require_website_in_tenant()`, mirroring
    `product/telephony/numbers.py::_require_phone_number_in_tenant()`)
    before ever attempting the insert -- an unknown `website_id` is
    rejected with the correct `WebsiteReferenceNotFoundError` (404), never
    mislabeled as a slug collision (409) by the composite FK's own
    `IntegrityError`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(WebsiteReferenceNotFoundError):
            create_page(
                owner.id, client.tenant_id, uuid.uuid4(), slug=_name("home"), title="Orphan"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_page_for_website_in_another_tenant_rejected() -> None:
    """The pre-validation is tenant-scoped, not just existence-scoped: a
    real website belonging to a *different* tenant is rejected the same
    way an unknown one is -- never `WebsiteSlugTakenError`, never a raw
    `IntegrityError`."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        site_a = _site(owner_a.id, client_a.tenant_id)
        with pytest.raises(WebsiteReferenceNotFoundError):
            create_page(
                owner_b.id, client_b.tenant_id, site_a.id, slug=_name("home"), title="Cross"
            )
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


# --- Lifecycle: draft/publish/unpublish, the content split -------------------


def test_publish_and_unpublish_lifecycle() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        blocks = [{"type": "paragraph", "text": "v1"}]
        page = create_page(
            owner.id,
            client.tenant_id,
            site.id,
            slug=_name("home"),
            title="Home",
            content_blocks=blocks,
        )
        published = publish_page(owner.id, client.tenant_id, page.id)
        assert published.status == STATUS_PUBLISHED
        assert published.published_content_blocks == blocks
        assert published.published_at is not None

        unpublished = unpublish_page(owner.id, client.tenant_id, page.id)
        assert unpublished.status == STATUS_DRAFT
        # Unpublishing does NOT discard the last snapshot.
        assert unpublished.published_content_blocks == blocks
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_draft_edit_after_publish_does_not_change_public_snapshot_until_republish() -> None:
    """The core security property of the draft/published split: editing
    `content_blocks` after publishing never mutates
    `published_content_blocks` -- only an explicit `publish_page()` call
    does."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        v1 = [{"type": "paragraph", "text": "v1"}]
        page = create_page(
            owner.id,
            client.tenant_id,
            site.id,
            slug=_name("home"),
            title="Home",
            content_blocks=v1,
        )
        publish_page(owner.id, client.tenant_id, page.id)

        v2 = [{"type": "paragraph", "text": "v2 -- unpublished edit"}]
        update_page(owner.id, client.tenant_id, page.id, content_blocks=v2)

        public = get_published_page(client.tenant_id, site.id, page.slug)
        assert public is not None
        assert public.content_blocks == v1  # still the v1 snapshot

        # A subsequent explicit publish picks up the new draft.
        publish_page(owner.id, client.tenant_id, page.id)
        public_after_republish = get_published_page(client.tenant_id, site.id, page.slug)
        assert public_after_republish is not None
        assert public_after_republish.content_blocks == v2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_published_page_returns_none_for_draft_page() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")
        assert get_published_page(client.tenant_id, site.id, page.slug) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_published_page_returns_none_after_unpublish() -> None:
    """Even though `published_content_blocks` is kept after unpublish
    (not discarded), `status != published` alone must hide it from the
    public read path."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")
        publish_page(owner.id, client.tenant_id, page.id)
        unpublish_page(owner.id, client.tenant_id, page.id)
        assert get_published_page(client.tenant_id, site.id, page.slug) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_published_page_returns_none_for_unknown_slug() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        assert get_published_page(client.tenant_id, site.id, "no-such-page") is None
        assert get_published_page(client.tenant_id, site.id, "Not A Slug!!") is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_published_page_view_excludes_draft_only_fields() -> None:
    """`PublishedPageView` has no `created_by_user_id`/`id` -- a public
    caller sees only the bounded fields, not internal metadata."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")
        publish_page(owner.id, client.tenant_id, page.id)
        public = get_published_page(client.tenant_id, site.id, page.slug)
        assert public is not None
        assert not hasattr(public, "created_by_user_id")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation (RLS-backed) --------------------------------------------


def test_pages_are_isolated_across_tenants() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        site_a = _site(owner_a.id, client_a.tenant_id)
        page_a = create_page(
            owner_a.id, client_a.tenant_id, site_a.id, slug=_name("home"), title="A"
        )

        with pytest.raises(WebsiteReferenceNotFoundError):
            get_page(owner_b.id, client_b.tenant_id, page_a.id)

        # Direct RLS proof, bypassing the service layer: a session scoped
        # to tenant B's own context can never see tenant A's row, even
        # via a raw, unfiltered SELECT.
        with tenant_session_scope(client_b.tenant_id) as session:
            row = session.get(Page, page_a.id)
            assert row is None
            rows = session.execute(select(Page)).scalars().all()
            assert all(r.id != page_a.id for r in rows)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_get_published_page_is_tenant_scoped_even_with_correct_website_id() -> None:
    """The public read takes `tenant_id` explicitly (supplied by the
    caller's own prior `resolve_website_by_slug()` call) -- passing
    tenant B's id can never surface tenant A's page, even with the
    correct `website_id`."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        site_a = _site(owner_a.id, client_a.tenant_id)
        page_a = create_page(
            owner_a.id, client_a.tenant_id, site_a.id, slug=_name("home"), title="A"
        )
        publish_page(owner_a.id, client_a.tenant_id, page_a.id)

        assert get_published_page(client_b.tenant_id, site_a.id, page_a.slug) is None
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


# --- Authorization -------------------------------------------------------------


def test_unrelated_actor_cannot_create_page() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        site = _site(owner.id, client.tenant_id)
        with pytest.raises(WebsiteAccessDeniedError):
            create_page(unrelated.id, client.tenant_id, site.id, slug=_name("home"), title="Nope")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_create_and_update_but_not_delete_page() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        site = _site(owner.id, client.tenant_id)
        page = create_page(
            member.id, client.tenant_id, site.id, slug=_name("home"), title="By Member"
        )
        update_page(member.id, client.tenant_id, page.id, title="Updated By Member")
        with pytest.raises(WebsiteAccessDeniedError):
            delete_page(member.id, client.tenant_id, page.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)
