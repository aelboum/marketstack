"""`product/websites/websites.py`: Website CRUD, global slug/custom-domain
uniqueness (the unscoped-table proof), tenant isolation, authorization,
and tenant-lifecycle denial (docs/ROADMAP.md Phase 11.1). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.websites.errors import (
    WebsiteAccessDeniedError,
    WebsiteReferenceNotFoundError,
    WebsiteSlugTakenError,
    WebsiteValidationError,
)
from product.websites.pagination import MAX_PAGE_SIZE
from product.websites.websites import (
    create_website,
    delete_website,
    get_website,
    list_websites,
    resolve_website_by_slug,
    update_website,
)

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


# --- CRUD, valid creation ----------------------------------------------------


def test_create_get_list_update_delete_website() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = create_website(owner.id, client.tenant_id, slug=_name("site"), name="My Site")
        assert site.tenant_id == client.tenant_id

        fetched = get_website(owner.id, client.tenant_id, site.id)
        assert fetched.id == site.id

        listed = list_websites(owner.id, client.tenant_id)
        assert any(w.id == site.id for w in listed)

        updated = update_website(owner.id, client.tenant_id, site.id, name="Renamed Site")
        assert updated.name == "Renamed Site"
        assert updated.custom_domain is None

        delete_website(owner.id, client.tenant_id, site.id)
        with pytest.raises(WebsiteReferenceNotFoundError):
            get_website(owner.id, client.tenant_id, site.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_website_with_custom_domain() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = create_website(
            owner.id,
            client.tenant_id,
            slug=_name("site"),
            name="Domained",
            custom_domain=f"{_name('example')}.com",
        )
        assert site.custom_domain is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- update_website(): the `...`-sentinel, omitted-vs-explicit-None ---------


def test_update_website_custom_domain_sentinel_distinguishes_omitted_from_clear() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = create_website(
            owner.id,
            client.tenant_id,
            slug=_name("site"),
            name="Domained",
            custom_domain=f"{_name('example')}.com",
        )
        original_domain = site.custom_domain

        # Omitted `custom_domain` -- must leave it untouched.
        unchanged = update_website(owner.id, client.tenant_id, site.id, name="New Name")
        assert unchanged.custom_domain == original_domain

        # Explicit `None` -- must clear it.
        cleared = update_website(owner.id, client.tenant_id, site.id, custom_domain=None)
        assert cleared.custom_domain is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input ------------------------------------------------------------


def test_create_website_rejects_empty_name() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(WebsiteValidationError):
            create_website(owner.id, client.tenant_id, slug=_name("site"), name="   ")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_website_rejects_invalid_slug() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(WebsiteValidationError):
            create_website(owner.id, client.tenant_id, slug="Not A Slug!", name="Bad Slug")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Uniqueness: the unscoped-table proof ------------------------------------


def test_slug_is_globally_unique_across_tenants() -> None:
    """The structural point of the whole unscoped-table design: two
    *different* tenants cannot both claim the same slug -- global, not
    per-tenant, uniqueness."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    shared_slug = _name("shared-slug")
    try:
        create_website(owner_a.id, client_a.tenant_id, slug=shared_slug, name="First")
        with pytest.raises(WebsiteSlugTakenError):
            create_website(owner_b.id, client_b.tenant_id, slug=shared_slug, name="Second")
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_slug_collision_is_case_insensitive() -> None:
    """Two raw inputs differing only in case normalize to the same slug
    (tests/websites/test_slugs_and_content_blocks_unit.py) and therefore
    collide at the database layer too."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    raw_slug = _name("CaseCollide")
    try:
        create_website(owner.id, client.tenant_id, slug=raw_slug, name="First")
        with pytest.raises(WebsiteSlugTakenError):
            create_website(owner.id, client.tenant_id, slug=raw_slug.upper(), name="Second")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_slug_is_unique_even_within_the_same_tenant() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    shared_slug = _name("same-tenant-slug")
    try:
        create_website(owner.id, client.tenant_id, slug=shared_slug, name="First")
        with pytest.raises(WebsiteSlugTakenError):
            create_website(owner.id, client.tenant_id, slug=shared_slug, name="Second")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_custom_domain_is_globally_unique() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    shared_domain = f"{_name('shared')}.example.com"
    try:
        create_website(
            owner_a.id,
            client_a.tenant_id,
            slug=_name("site"),
            name="First",
            custom_domain=shared_domain,
        )
        with pytest.raises(WebsiteSlugTakenError):
            create_website(
                owner_b.id,
                client_b.tenant_id,
                slug=_name("site"),
                name="Second",
                custom_domain=shared_domain,
            )
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_update_website_custom_domain_collision_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        taken_domain = f"{_name('taken')}.example.com"
        create_website(
            owner.id, client.tenant_id, slug=_name("site-a"), name="A", custom_domain=taken_domain
        )
        second = create_website(owner.id, client.tenant_id, slug=_name("site-b"), name="B")
        with pytest.raises(WebsiteSlugTakenError):
            update_website(owner.id, client.tenant_id, second.id, custom_domain=taken_domain)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation ---------------------------------------------------------


def test_websites_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        site = create_website(owner.id, client.tenant_id, slug=_name("site"), name="Mine")
        with pytest.raises(WebsiteReferenceNotFoundError):
            get_website(other_owner.id, other_client.tenant_id, site.id)
        listed = list_websites(other_owner.id, other_client.tenant_id)
        assert all(w.id != site.id for w in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_websites_isolated_even_though_table_carries_no_rls() -> None:
    """The unscoped table's own isolation guarantee comes from the
    service layer's explicit `tenant_id` filter
    (`product/websites/websites.py::_get_owned_row()`), not from
    Postgres RLS -- proven directly here since `websites.websites` has
    no RLS policy at all (unlike `websites.pages`)."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        site_a = create_website(owner_a.id, client_a.tenant_id, slug=_name("site"), name="A")
        with pytest.raises(WebsiteReferenceNotFoundError):
            get_website(owner_b.id, client_b.tenant_id, site_a.id)
        # owner_b genuinely holds `delete` on their OWN tenant (client_b),
        # so require() passes -- the cross-tenant lookup inside
        # _get_owned_row() is what correctly fails here, the same shape
        # tests/telephony/test_numbers_integration.py
        # ::test_phone_numbers_are_isolated_across_tenants already proves
        # for its own unscoped table's cross-tenant read.
        with pytest.raises(WebsiteReferenceNotFoundError):
            delete_website(owner_b.id, client_b.tenant_id, site_a.id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


# --- Authorization -------------------------------------------------------------


def test_unrelated_actor_cannot_create_website() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(WebsiteAccessDeniedError):
            create_website(unrelated.id, client.tenant_id, slug=_name("site"), name="Nope")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_create_and_read_but_not_delete() -> None:
    """`product/websites/event_handlers.py`'s own owner/member grant
    split: member gets create/read/update, never delete."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        site = create_website(member.id, client.tenant_id, slug=_name("site"), name="By Member")
        fetched = get_website(member.id, client.tenant_id, site.id)
        assert fetched.id == site.id
        with pytest.raises(WebsiteAccessDeniedError):
            delete_website(member.id, client.tenant_id, site.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_agency_owner_reaches_own_clients_websites_via_inherited_subtree() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = create_website(owner.id, client.tenant_id, slug=_name("site"), name="Inherited")
        assert site.tenant_id == client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant lifecycle ----------------------------------------------------------


def test_suspended_tenant_denies_website_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_website(owner.id, client.tenant_id, slug=_name("site"), name="Before Suspend")
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(WebsiteAccessDeniedError):
            create_website(owner.id, client.tenant_id, slug=_name("site"), name="After Suspend")
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Public, untenanted slug resolution ---------------------------------------


def test_resolve_website_by_slug_public_lookup() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        raw_slug = _name("Public-Slug")
        site = create_website(owner.id, client.tenant_id, slug=raw_slug, name="Public")
        resolved = resolve_website_by_slug(raw_slug.upper())
        assert resolved is not None
        assert resolved.id == site.id
        assert resolved.tenant_id == client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_resolve_website_by_slug_unknown_returns_none() -> None:
    assert resolve_website_by_slug("totally-unknown-slug") is None


def test_resolve_website_by_slug_malformed_returns_none_not_raise() -> None:
    """A malformed slug fails closed to `None` (a non-enumerating 404 at
    the API layer), never an unhandled `WebsiteValidationError`."""
    assert resolve_website_by_slug("Not A Slug!!") is None
    assert resolve_website_by_slug("") is None


# --- Pagination ------------------------------------------------------------


def test_list_websites_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for _ in range(3):
            create_website(owner.id, client.tenant_id, slug=_name("site"), name="Bulk")
        results = list_websites(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
