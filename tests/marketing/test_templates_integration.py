"""Templates (docs/ROADMAP.md Phase 6.4): CRUD, clone, uniqueness, and
the campaign one-time-copy-in semantics. Real disposable Postgres.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.marketing.campaigns import create_campaign, get_campaign
from product.marketing.errors import MarketingReferenceNotFoundError, MarketingValidationError
from product.marketing.templates import (
    clone_template,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_template_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        template = create_template(
            owner.id,
            client.tenant_id,
            name="Welcome Email",
            template_type="email_campaign",
            content="Hello {{name}}!",
        )
        assert template.content == "Hello {{name}}!"

        fetched = get_template(owner.id, client.tenant_id, template.id)
        assert fetched.id == template.id

        updated = update_template(owner.id, client.tenant_id, template.id, content="Updated body")
        assert updated.content == "Updated body"

        listed = list_templates(owner.id, client.tenant_id)
        assert any(t.id == template.id for t in listed)

        delete_template(owner.id, client.tenant_id, template.id)
        with pytest.raises(MarketingReferenceNotFoundError):
            get_template(owner.id, client.tenant_id, template.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_template_name_unique_per_tenant() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_template(
            owner.id, client.tenant_id, name="Dup", template_type="email_campaign", content="a"
        )
        with pytest.raises(MarketingValidationError):
            create_template(
                owner.id, client.tenant_id, name="Dup", template_type="sms_campaign", content="b"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invalid_template_type_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(MarketingValidationError):
            create_template(
                owner.id, client.tenant_id, name="Bad", template_type="not_a_type", content="x"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_clone_template_copies_content_under_new_name() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        original = create_template(
            owner.id,
            client.tenant_id,
            name="Original",
            template_type="landing_page",
            content="<h1>Original</h1>",
        )
        cloned = clone_template(owner.id, client.tenant_id, original.id, new_name="Clone")
        assert cloned.id != original.id
        assert cloned.name == "Clone"
        assert cloned.content == original.content
        assert cloned.template_type == original.template_type
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_clone_template_rejects_colliding_name() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        original = create_template(
            owner.id, client.tenant_id, name="Original", template_type="email_campaign", content="x"
        )
        create_template(
            owner.id, client.tenant_id, name="Taken", template_type="email_campaign", content="y"
        )
        with pytest.raises(MarketingValidationError):
            clone_template(owner.id, client.tenant_id, original.id, new_name="Taken")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_campaign_from_template_is_a_one_time_copy_not_a_live_reference() -> None:
    """Editing a template after a campaign was created from it does NOT
    change the campaign's own stored body -- the explicit, chosen
    semantics (product/marketing/campaigns.py::_copy_in_template)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        template = create_template(
            owner.id,
            client.tenant_id,
            name="Source",
            template_type="email_campaign",
            content="Original template body",
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="From Template",
            channel="email",
            body="",
            subject="Hi",
            template_id=template.id,
        )
        assert campaign.body == "Original template body"
        assert campaign.template_id == template.id

        update_template(owner.id, client.tenant_id, template.id, content="EDITED body")

        unchanged = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert unchanged.body == "Original template body"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_campaign_with_unknown_template_id_fails_closed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(MarketingReferenceNotFoundError):
            create_campaign(
                owner.id,
                client.tenant_id,
                name="Bad Template",
                channel="email",
                body="",
                subject="Hi",
                template_id=uuid.uuid4(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_deleting_template_unlinks_campaign_rather_than_breaking_it() -> None:
    """Column-scoped ON DELETE SET NULL (template_id) -- the fix for the
    defect class the deferred Phase 4 CRM bug demonstrated."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        template = create_template(
            owner.id, client.tenant_id, name="ToDelete", template_type="email_campaign", content="x"
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="Linked",
            channel="email",
            body="",
            subject="Hi",
            template_id=template.id,
        )
        delete_template(owner.id, client.tenant_id, template.id)

        refreshed = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert refreshed.template_id is None
        assert refreshed.body == "x"  # already-copied body untouched
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
