"""Outbound call initiation, list/get, authorization
(docs/ROADMAP.md Phase 8.2). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.telephony.calls import (
    get_call,
    initiate_outbound_call,
    list_calls,
)
from product.telephony.errors import (
    TelephonyAccessDeniedError,
    TelephonyProviderError,
    TelephonyReferenceNotFoundError,
    TelephonyValidationError,
)
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_initiate_outbound_call_success() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        call = initiate_outbound_call(
            owner.id,
            client.tenant_id,
            phone_number_id=number.id,
            to_number="+15559998888",
            provider=provider,
        )
        assert call.status == "ringing"
        assert call.direction == "outbound"
        assert call.from_number == number.phone_number
        assert call.provider_call_id is not None

        fetched = get_call(owner.id, client.tenant_id, call.id)
        assert fetched.id == call.id

        listed = list_calls(owner.id, client.tenant_id)
        assert any(c.id == call.id for c in listed)
        listed_outbound = list_calls(owner.id, client.tenant_id, direction="outbound")
        assert any(c.id == call.id for c in listed_outbound)
        listed_inbound = list_calls(owner.id, client.tenant_id, direction="inbound")
        assert not any(c.id == call.id for c in listed_inbound)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_initiate_outbound_call_provider_failure_marks_call_failed() -> None:
    """Provider failures must fail safely (this phase's own explicit
    requirement) -- the Call row must accurately reflect `failed`, not be
    left dangling in `ringing`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        failing_provider = FakeTelephonyProvider(webhook_secret="s", fail=True)
        with pytest.raises(TelephonyProviderError):
            initiate_outbound_call(
                owner.id,
                client.tenant_id,
                phone_number_id=number.id,
                to_number="+15559998888",
                provider=failing_provider,
            )
        listed = list_calls(owner.id, client.tenant_id)
        assert len(listed) == 1
        assert listed[0].status == "failed"
        assert listed[0].ended_at is not None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_initiate_outbound_call_empty_to_number_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        with pytest.raises(TelephonyValidationError):
            initiate_outbound_call(
                owner.id,
                client.tenant_id,
                phone_number_id=number.id,
                to_number="",
                provider=provider,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_initiate_outbound_call_unknown_phone_number_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        with pytest.raises(TelephonyReferenceNotFoundError):
            initiate_outbound_call(
                owner.id,
                client.tenant_id,
                phone_number_id=uuid.uuid4(),
                to_number="+15559998888",
                provider=provider,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_initiate_call() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        with pytest.raises(TelephonyAccessDeniedError):
            initiate_outbound_call(
                unrelated.id,
                client.tenant_id,
                phone_number_id=number.id,
                to_number="+15559998888",
                provider=provider,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_calls_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    provider = FakeTelephonyProvider(webhook_secret="s")
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=provider
        )
        call = initiate_outbound_call(
            owner.id,
            client.tenant_id,
            phone_number_id=number.id,
            to_number="+15559998888",
            provider=provider,
        )
        with pytest.raises(TelephonyReferenceNotFoundError):
            get_call(other_owner.id, other_client.tenant_id, call.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_list_calls_empty_for_new_tenant() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        assert list_calls(owner.id, client.tenant_id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
