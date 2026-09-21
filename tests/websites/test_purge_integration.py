"""`product/websites/purge.py`: the two tenant-purge participants (one
RLS-scoped for `websites.pages`, one unscoped for `websites.websites`),
and their tenant-scoping -- purging tenant A must never touch tenant B's
rows (docs/ROADMAP.md Phase 11.1). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from infra.db import select, session_scope, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.websites.models import Page, Website
from product.websites.pages import create_page
from product.websites.purge import (
    WebsitesDataPurgeParticipant,
    WebsitesUnscopedDataPurgeParticipant,
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


def test_purge_deletes_only_the_target_tenants_websites_and_pages() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        site_a = create_website(owner_a.id, client_a.tenant_id, slug=_name("site"), name="A")
        page_a = create_page(
            owner_a.id, client_a.tenant_id, site_a.id, slug=_name("home"), title="A Home"
        )
        site_b = create_website(owner_b.id, client_b.tenant_id, slug=_name("site"), name="B")
        page_b = create_page(
            owner_b.id, client_b.tenant_id, site_b.id, slug=_name("home"), title="B Home"
        )

        WebsitesDataPurgeParticipant().purge_tenant_data(client_a.tenant_id)
        WebsitesUnscopedDataPurgeParticipant().purge_tenant_data(client_a.tenant_id)

        with session_scope() as session:
            assert session.get(Website, site_a.id) is None
            assert session.get(Website, site_b.id) is not None

        with tenant_session_scope(client_b.tenant_id) as session:
            row = session.get(Page, page_b.id)
            assert row is not None
            assert row.id == page_b.id

        # Tenant A's page row is truly gone, not merely RLS-hidden --
        # proven via the admin, untenanted connection.
        with session_scope() as session:
            leftover = (
                session.execute(select(Page).where(Page.tenant_id == client_a.tenant_id))
                .scalars()
                .all()
            )
            assert leftover == []
            assert all(row.id != page_a.id for row in leftover)
    finally:
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        # Tenant A's own rows are already purged above; cleanup_tenant_tree
        # is still idempotent-safe to call (DELETE ... WHERE matches
        # nothing) so it also tears down tenant A's core.* rows.
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_purge_participants_are_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        site = create_website(owner.id, client.tenant_id, slug=_name("site"), name="Once")
        create_page(owner.id, client.tenant_id, site.id, slug=_name("home"), title="Home")

        pages_participant = WebsitesDataPurgeParticipant()
        websites_participant = WebsitesUnscopedDataPurgeParticipant()
        pages_participant.purge_tenant_data(client.tenant_id)
        websites_participant.purge_tenant_data(client.tenant_id)
        # A second run against an already-empty tenant must not raise.
        pages_participant.purge_tenant_data(client.tenant_id)
        websites_participant.purge_tenant_data(client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
