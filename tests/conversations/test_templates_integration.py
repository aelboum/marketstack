"""Reusable message templates (docs/ROADMAP.md Phase 5.5). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.conversations.errors import (
    ConversationAccessDeniedError,
    ConversationReferenceNotFoundError,
    ConversationValidationError,
)
from product.conversations.templates import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

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
            owner.id, client.tenant_id, name="Welcome", body="Hi there!", channel="email"
        )
        assert template.name == "Welcome"

        fetched = get_template(owner.id, client.tenant_id, template.id)
        assert fetched.id == template.id

        listed = list_templates(owner.id, client.tenant_id)
        assert any(t.id == template.id for t in listed)

        updated = update_template(
            owner.id, client.tenant_id, template.id, body="Hi there, updated!"
        )
        assert updated.body == "Hi there, updated!"

        delete_template(owner.id, client.tenant_id, template.id)
        with pytest.raises(ConversationReferenceNotFoundError):
            get_template(owner.id, client.tenant_id, template.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_template_name_unique_per_tenant() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_template(owner.id, client.tenant_id, name="Dup", body="one")
        with pytest.raises(ConversationValidationError):
            create_template(owner.id, client.tenant_id, name="Dup", body="two")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_same_template_name_allowed_across_different_tenants() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        t_a = create_template(owner_a.id, client_a.tenant_id, name="Shared Name", body="a")
        t_b = create_template(owner_b.id, client_b.tenant_id, name="Shared Name", body="b")
        assert t_a.id != t_b.id
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_invalid_channel_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ConversationValidationError):
            create_template(owner.id, client.tenant_id, name="Bad", body="x", channel="fax")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_client_template_read_denied() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        template_b = create_template(owner_b.id, client_b.tenant_id, name="B Only", body="x")
        with pytest.raises(ConversationAccessDeniedError):
            get_template(owner_a.id, client_b.tenant_id, template_b.id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)
