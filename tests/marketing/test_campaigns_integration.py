"""Campaign CRUD, lifecycle, and isolation (docs/ROADMAP.md Phase 6.1).
Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import RoleScope
from core.tenancy import TenantStatus, transition_tenant_status
from infra.db import IntegrityError, tenant_session_scope
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.marketing.campaigns import (
    cancel_campaign,
    create_campaign,
    delete_campaign,
    get_campaign,
    list_campaigns,
    update_campaign,
)
from product.marketing.errors import MarketingAccessDeniedError, MarketingValidationError
from product.marketing.models import MarketingCampaignRecipient
from product.marketing.permissions import CAMPAIGN_RESOURCE

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_campaign_crud_and_status_transitions() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="Welcome Series",
            channel="email",
            subject="Hello!",
            body="Welcome aboard.",
        )
        assert campaign.status == "draft"

        fetched = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert fetched.id == campaign.id

        listed = list_campaigns(owner.id, client.tenant_id)
        assert any(c.id == campaign.id for c in listed)

        updated = update_campaign(owner.id, client.tenant_id, campaign.id, name="Welcome Series v2")
        assert updated.name == "Welcome Series v2"

        delete_campaign(owner.id, client.tenant_id, campaign.id)
        with pytest.raises(Exception):  # noqa: B017 -- MarketingReferenceNotFoundError
            get_campaign(owner.id, client.tenant_id, campaign.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_campaign_requires_subject_for_email_channel() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(MarketingValidationError):
            create_campaign(
                owner.id, client.tenant_id, name="No Subject", channel="email", body="x"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_campaign_cannot_be_deleted_once_not_draft() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Locked", channel="email", subject="s", body="b"
        )
        with tenant_session_scope(client.tenant_id) as session:
            from product.marketing.models import MarketingCampaign

            row = session.get(MarketingCampaign, campaign.id)
            assert row is not None
            row.status = "sending"
            session.flush()

        with pytest.raises(MarketingValidationError):
            delete_campaign(owner.id, client.tenant_id, campaign.id)
        with pytest.raises(MarketingValidationError):
            update_campaign(owner.id, client.tenant_id, campaign.id, name="Should Fail")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancel_campaign_only_while_sending() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Cancel Me", channel="email", subject="s", body="b"
        )
        with pytest.raises(MarketingValidationError):
            cancel_campaign(owner.id, client.tenant_id, campaign.id)  # still 'draft'

        with tenant_session_scope(client.tenant_id) as session:
            from product.marketing.models import MarketingCampaign

            row = session.get(MarketingCampaign, campaign.id)
            assert row is not None
            row.status = "sending"
            session.flush()

        cancelled = cancel_campaign(owner.id, client.tenant_id, campaign.id)
        assert cancelled.status == "cancelled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_client_campaign_read_denied() -> None:
    """Requirement 2: a client A member (with no reach into client B) is
    denied reading client B's campaigns."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        campaign_b = create_campaign(
            owner_b.id, client_b.tenant_id, name="B Only", channel="email", subject="s", body="b"
        )
        with pytest.raises(MarketingAccessDeniedError):
            get_campaign(owner_a.id, client_b.tenant_id, campaign_b.id)
        with pytest.raises(MarketingAccessDeniedError):
            list_campaigns(owner_a.id, client_b.tenant_id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_agency_campaign_mutation_denied() -> None:
    """Requirement: cross-tenant mutation denied."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        campaign_b = create_campaign(
            owner_b.id, client_b.tenant_id, name="B Only", channel="email", subject="s", body="b"
        )
        with pytest.raises(MarketingAccessDeniedError):
            update_campaign(owner_a.id, client_b.tenant_id, campaign_b.id, name="Hijacked")
        with pytest.raises(MarketingAccessDeniedError):
            delete_campaign(owner_a.id, client_b.tenant_id, campaign_b.id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_owner_reaches_own_clients_campaigns_via_inherited_subtree() -> None:
    """Requirement 3/5: the agency owner (no direct membership at the
    client, only inherited SUBTREE reach from provision_agency()) can
    read/write the client's own campaigns."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Reach Test", channel="email", subject="s", body="b"
        )
        fetched = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert fetched.id == campaign.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_mutate_real_tenants_campaigns() -> None:
    """Requirement 6: a real, existing, syntactically valid tenant_id
    this actor has no relationship to."""
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(MarketingAccessDeniedError):
            create_campaign(
                stranger.id,
                client.tenant_id,
                name="Should Fail",
                channel="email",
                subject="s",
                body="b",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_explicit_deny_overrides_inherited_subtree_reach_for_marketing() -> None:
    """The agency owner's SUBTREE role reaches the client's marketing
    data by default; an explicit deny on the specific marketing
    permission, at the client tenant, removes it there -- mirrors
    tests/crm/test_isolation_integration.py
    ::test_explicit_deny_overrides_inherited_subtree_reach_for_crm's shape."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Visible", channel="email", subject="s", body="b"
        )
        assert campaign.id is not None

        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=CAMPAIGN_RESOURCE,
            action="create",
            scope_mode=RoleScope.SELF,
        )

        with pytest.raises(MarketingAccessDeniedError):
            create_campaign(
                owner.id,
                client.tenant_id,
                name="Should Fail",
                channel="email",
                subject="s",
                body="b",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_suspended_client_tenant_denies_marketing_mutation() -> None:
    """Requirement 7: deleted/suspended/purged tenants cannot continue
    operating on marketing records."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_campaign(
            owner.id,
            client.tenant_id,
            name="Before Suspend",
            channel="email",
            subject="s",
            body="b",
        )
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(MarketingAccessDeniedError):
            create_campaign(
                owner.id,
                client.tenant_id,
                name="After Suspend",
                channel="email",
                subject="s",
                body="b",
            )
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_campaigns_pagination_is_bounded() -> None:
    """API security requirement: bounded list/search results."""
    from product.marketing.pagination import MAX_PAGE_SIZE

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for i in range(3):
            create_campaign(
                owner.id, client.tenant_id, name=f"C{i}", channel="email", subject="s", body="b"
            )
        results = list_campaigns(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_campaign_reference_rejected_by_database_constraint_directly() -> None:
    """The composite FK on campaign_recipients.campaign_id is what
    actually enforces same-tenant campaign references at the database
    level -- proven by bypassing the service layer entirely."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        campaign_b = create_campaign(
            owner_b.id,
            client_b.tenant_id,
            name="B Campaign",
            channel="email",
            subject="s",
            body="b",
        )
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = MarketingCampaignRecipient(
                    tenant_id=client_a.tenant_id,
                    campaign_id=campaign_b.id,
                    status="pending",
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)
