"""Open/click tracking and engagement segmentation (docs/ROADMAP.md Phase
6.5). Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run. The open-redirect-safety proof is the highest-
priority test in this file.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from infra.db import select, session_scope, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.crm.contacts import create_contact
from product.marketing.campaigns import create_campaign
from product.marketing.models import MarketingCampaignRecipient, MarketingRecipientTrackingToken
from product.marketing.segmentation import EngagementFilter, SegmentQuery, resolve_segment
from product.marketing.sending import start_campaign_send
from product.marketing.tracking import (
    FALLBACK_REDIRECT_PATH,
    record_click_and_resolve_target,
    record_open,
)

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


async def _send_and_get_recipient(owner_id, client_tenant_id, campaign_id):
    await start_campaign_send(owner_id, client_tenant_id, campaign_id)
    with tenant_session_scope(client_tenant_id) as session:
        row = (
            session.execute(
                select(MarketingCampaignRecipient).where(
                    MarketingCampaignRecipient.tenant_id == client_tenant_id,
                    MarketingCampaignRecipient.campaign_id == campaign_id,
                )
            )
            .scalars()
            .one()
        )
        return row.id


def _tracking_token_for(client_tenant_id, recipient_id) -> str:
    with session_scope() as session:
        row = (
            session.execute(
                select(MarketingRecipientTrackingToken).where(
                    MarketingRecipientTrackingToken.recipient_id == recipient_id
                )
            )
            .scalars()
            .one()
        )
        return row.tracking_token


async def test_open_pixel_is_idempotent_first_open_wins() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Track", last_name="Ed", email="track@ex.com"
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Track", channel="email", body="b", subject="s"
        )
        recipient_id = await _send_and_get_recipient(owner.id, client.tenant_id, campaign.id)
        token = _tracking_token_for(client.tenant_id, recipient_id)

        record_open(token)
        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(MarketingCampaignRecipient, recipient_id)
            assert row is not None
            first_opened_at = row.opened_at
        assert first_opened_at is not None

        record_open(token)  # second fetch, same pixel
        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(MarketingCampaignRecipient, recipient_id)
            assert row is not None
            assert row.opened_at == first_opened_at  # unchanged, first-open wins
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_open_pixel_never_raises_for_unknown_token() -> None:
    record_open("totally-unknown-tracking-token")  # must not raise


async def test_click_redirects_to_campaigns_own_stored_target_url() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Click", last_name="Er", email="click@ex.com"
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="ClickTrack",
            channel="email",
            body="b",
            subject="s",
            click_target_url="https://real-destination.example.com/landing",
        )
        recipient_id = await _send_and_get_recipient(owner.id, client.tenant_id, campaign.id)
        token = _tracking_token_for(client.tenant_id, recipient_id)

        target = record_click_and_resolve_target(token)
        assert target == "https://real-destination.example.com/landing"

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(MarketingCampaignRecipient, recipient_id)
            assert row is not None
            assert row.clicked_at is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_click_unknown_token_redirects_to_fallback_not_an_error() -> None:
    target = record_click_and_resolve_target("totally-unknown-tracking-token")
    assert target == FALLBACK_REDIRECT_PATH


async def test_click_endpoint_is_immune_to_caller_supplied_redirect_target() -> None:
    """The single highest-priority test in this file: an attacker
    attempting to pass a `?url=`/`?redirect=`/`?next=`-shaped query
    parameter on the click endpoint has zero effect on the redirect
    target, which is always and only the campaign's own server-stored
    `click_target_url`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Safe", last_name="Guard", email="safe@ex.com"
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="RedirectSafety",
            channel="email",
            body="b",
            subject="s",
            click_target_url="https://the-real-target.example.com/",
        )
        recipient_id = await _send_and_get_recipient(owner.id, client.tenant_id, campaign.id)
        token = _tracking_token_for(client.tenant_id, recipient_id)

        api = TestClient(create_app(), follow_redirects=False)
        for malicious_query in (
            "?url=https://evil.example.com",
            "?redirect=https://evil.example.com",
            "?next=https://evil.example.com",
            "?url=javascript:alert(1)",
        ):
            response = api.get(f"/v1/marketing/track/click/{token}{malicious_query}")
            assert response.status_code == 302
            assert response.headers["location"] == "https://the-real-target.example.com/"
            assert "evil.example.com" not in response.headers["location"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_open_pixel_over_http_returns_a_real_gif_never_a_404() -> None:
    api = TestClient(create_app())
    response = api.get("/v1/marketing/track/open/totally-unknown-token")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"


async def test_engagement_segmentation_opened_campaign() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        opened_contact = create_contact(
            owner.id, client.tenant_id, first_name="Opened", last_name="It", email="opened@ex.com"
        )
        not_opened_contact = create_contact(
            owner.id, client.tenant_id, first_name="Never", last_name="Opened", email="never@ex.com"
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="EngageSrc", channel="email", body="b", subject="s"
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)

        with tenant_session_scope(client.tenant_id) as session:
            recipients = (
                session.execute(
                    select(MarketingCampaignRecipient).where(
                        MarketingCampaignRecipient.tenant_id == client.tenant_id,
                        MarketingCampaignRecipient.campaign_id == campaign.id,
                    )
                )
                .scalars()
                .all()
            )
            opened_recipient_id = next(
                r.id for r in recipients if r.contact_id == opened_contact.id
            )

        token = _tracking_token_for(client.tenant_id, opened_recipient_id)
        record_open(token)

        engaged = resolve_segment(
            owner.id,
            client.tenant_id,
            SegmentQuery(engagement=EngagementFilter(opened_campaign_id=campaign.id)),
        )
        engaged_ids = {c.id for c in engaged}
        assert opened_contact.id in engaged_ids
        assert not_opened_contact.id not in engaged_ids
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
