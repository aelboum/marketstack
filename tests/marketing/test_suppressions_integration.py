"""Suppression list CRUD and the `is_suppressed()` hard gate
(docs/ROADMAP.md Phase 6.1's own explicit security requirement). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from infra.db import IntegrityError, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import create_contact
from product.marketing.errors import MarketingAccessDeniedError, MarketingReferenceNotFoundError
from product.marketing.models import MarketingSuppression
from product.marketing.suppressions import (
    create_suppression,
    delete_suppression,
    is_suppressed,
    list_suppressions,
)

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_client_and_contact(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    contact = create_contact(owner_id, client.tenant_id, first_name="Sup", last_name="Pressed")
    return agency, client, contact


def test_suppression_create_list_delete_and_gate() -> None:
    owner = make_user()
    agency, client, contact = _agency_client_and_contact(owner.id)
    try:
        assert is_suppressed(client.tenant_id, contact.id, "email") is False

        suppression = create_suppression(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            channel="email",
            reason="unsubscribed",
        )
        assert suppression.contact_id == contact.id

        assert is_suppressed(client.tenant_id, contact.id, "email") is True
        assert (
            is_suppressed(client.tenant_id, contact.id, "sms") is False
        )  # per-channel, not global

        listed = list_suppressions(owner.id, client.tenant_id)
        assert any(s.id == suppression.id for s in listed)

        delete_suppression(owner.id, client.tenant_id, suppression.id)
        assert is_suppressed(client.tenant_id, contact.id, "email") is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_suppression_same_contact_channel_rejected_by_database_directly() -> None:
    """UNIQUE(tenant_id, contact_id, channel) proven at the database
    level, bypassing the service layer."""
    owner = make_user()
    agency, client, contact = _agency_client_and_contact(owner.id)
    try:
        create_suppression(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email", reason="manual"
        )
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client.tenant_id) as session:
                row = MarketingSuppression(
                    tenant_id=client.tenant_id,
                    contact_id=contact.id,
                    channel="email",
                    reason="manual",
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_contact_reference_rejected_by_database_constraint_directly() -> None:
    """A suppression in tenant A cannot reference a contact from tenant
    B -- proven at the database level."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a, contact_a = _agency_client_and_contact(owner_a.id)
    agency_b, client_b, contact_b = _agency_client_and_contact(owner_b.id)
    try:
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = MarketingSuppression(
                    tenant_id=client_a.tenant_id,
                    contact_id=contact_b.id,
                    channel="email",
                    reason="manual",
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_client_suppression_read_denied() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a, contact_a = _agency_client_and_contact(owner_a.id)
    agency_b, client_b, contact_b = _agency_client_and_contact(owner_b.id)
    try:
        create_suppression(
            owner_b.id,
            client_b.tenant_id,
            contact_id=contact_b.id,
            channel="email",
            reason="manual",
        )
        with pytest.raises(MarketingAccessDeniedError):
            list_suppressions(owner_a.id, client_b.tenant_id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_delete_unknown_suppression_fails_closed() -> None:
    owner = make_user()
    agency, client, contact = _agency_client_and_contact(owner.id)
    try:
        with pytest.raises(MarketingReferenceNotFoundError):
            delete_suppression(owner.id, client.tenant_id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
