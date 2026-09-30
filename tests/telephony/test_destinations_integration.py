"""`product/telephony/destinations.py` -- the approved Phase 27.0
human-destination boundary. Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.telephony.destinations import (
    get_human_transfer_destination,
    resolve_human_destination,
    set_human_transfer_destination,
)
from product.telephony.errors import TelephonyAccessDeniedError, TelephonyValidationError
from product.telephony.models import DESTINATION_KIND_E164

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_set_and_get_human_transfer_destination() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        result = set_human_transfer_destination(
            owner.id, client.tenant_id, e164_value="+31612345678"
        )
        assert result.kind == DESTINATION_KIND_E164
        assert result.value == "+31612345678"

        fetched = get_human_transfer_destination(owner.id, client.tenant_id)
        assert fetched is not None
        assert fetched.value == "+31612345678"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_set_replaces_the_single_existing_destination() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+14155550123")
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+212600000000")

        fetched = get_human_transfer_destination(owner.id, client.tenant_id)
        assert fetched is not None
        assert fetched.value == "+212600000000"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_no_destination_configured_returns_none() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        assert get_human_transfer_destination(owner.id, client.tenant_id) is None
        assert resolve_human_destination(client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_malformed_destination_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(TelephonyValidationError):
            set_human_transfer_destination(owner.id, client.tenant_id, e164_value="not-a-number")
        assert get_human_transfer_destination(owner.id, client.tenant_id) is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_destinations_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        assert resolve_human_destination(other_client.tenant_id) is None
        with pytest.raises(TelephonyAccessDeniedError):
            get_human_transfer_destination(other_owner.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_unrelated_actor_cannot_set_a_destination() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(TelephonyAccessDeniedError):
            set_human_transfer_destination(
                unrelated.id, client.tenant_id, e164_value="+31612345678"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)
