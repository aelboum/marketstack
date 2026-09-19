"""Contact/company CRUD and isolation (docs/ROADMAP.md Phase 4.1). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from infra.db import IntegrityError, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.crm.companies import (
    create_company,
    delete_company,
    get_company,
    update_company,
)
from product.crm.contacts import (
    create_contact,
    delete_contact,
    get_contact,
    list_contacts,
    update_contact,
)
from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError
from product.crm.models import Contact
from product.foundation.values import InvalidPhoneNumberError

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_company_and_contact_crud() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        company = create_company(owner.id, client.tenant_id, name="Acme Corp", domain="acme.test")
        assert company.name == "Acme Corp"

        fetched = get_company(owner.id, client.tenant_id, company.id)
        assert fetched.id == company.id

        updated = update_company(owner.id, client.tenant_id, company.id, name="Acme Corp Renamed")
        assert updated.name == "Acme Corp Renamed"

        contact = create_contact(
            owner.id,
            client.tenant_id,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+15551234567",
            company_id=company.id,
        )
        assert contact.company_id == company.id
        assert contact.phone == "+15551234567"

        listed = list_contacts(owner.id, client.tenant_id)
        assert any(c.id == contact.id for c in listed)

        updated_contact = update_contact(owner.id, client.tenant_id, contact.id, last_name="Byron")
        assert updated_contact.last_name == "Byron"

        delete_contact(owner.id, client.tenant_id, contact.id)
        with pytest.raises(CrmReferenceNotFoundError):
            get_contact(owner.id, client.tenant_id, contact.id)

        delete_company(owner.id, client.tenant_id, company.id)
        with pytest.raises(CrmReferenceNotFoundError):
            get_company(owner.id, client.tenant_id, company.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_contact_phone_is_normalized_and_invalid_phone_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="A", last_name="B", phone="00 44 20 7946 0958"
        )
        assert contact.phone == "+442079460958"

        with pytest.raises(InvalidPhoneNumberError):
            create_contact(
                owner.id, client.tenant_id, first_name="A", last_name="B", phone="not-a-phone"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_contact_cross_tenant_company_reference_denied_at_service_layer() -> None:
    """Requirement: cross-tenant relationship creation denied. A contact
    in client A's tenant cannot reference a company that lives in client
    B's tenant -- product/crm/contacts.py's own pre-check raises before
    any write is attempted."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        company_b = create_company(owner_b.id, client_b.tenant_id, name="Other Tenant Co")
        with pytest.raises(CrmReferenceNotFoundError):
            create_contact(
                owner_a.id,
                client_a.tenant_id,
                first_name="Cross",
                last_name="Tenant",
                company_id=company_b.id,
            )
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_tenant_company_reference_rejected_by_database_constraint_directly() -> None:
    """The composite FK itself is what actually enforces this, not just
    the service-layer pre-check above -- proven by bypassing the service
    layer entirely and attempting the insert directly."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        company_b = create_company(owner_b.id, client_b.tenant_id, name="Other Tenant Co")
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = Contact(
                    tenant_id=client_a.tenant_id,
                    first_name="Direct",
                    last_name="Insert",
                    company_id=company_b.id,
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_cross_client_contact_read_denied() -> None:
    """Requirement 2: a client A member (with no reach into client B) is
    denied reading client B's contacts."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        contact_b = create_contact(owner_b.id, client_b.tenant_id, first_name="B", last_name="Only")
        with pytest.raises(CrmAccessDeniedError):
            get_contact(owner_a.id, client_b.tenant_id, contact_b.id)
        with pytest.raises(CrmAccessDeniedError):
            list_contacts(owner_a.id, client_b.tenant_id)
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_agency_owner_reaches_own_clients_contacts_via_inherited_subtree() -> None:
    """Requirement 3/5: the agency owner (no direct membership at the
    client, only inherited SUBTREE reach from provision_agency()) can
    read/write the client's own contacts."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Reach", last_name="Test")
        fetched = get_contact(owner.id, client.tenant_id, contact.id)
        assert fetched.id == contact.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_mutate_real_tenants_contacts() -> None:
    """Requirement 6: a real, existing, syntactically valid tenant_id
    that this actor simply has no relationship to."""
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(CrmAccessDeniedError):
            create_contact(stranger.id, client.tenant_id, first_name="Should", last_name="Fail")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_client_member_with_read_only_cannot_delete() -> None:
    """A client's own baseline 'member' role is granted create/read/
    update but NOT delete (product/crm/event_handlers.py's own
    deliberate design choice) -- an unauthorized mutation is denied."""
    from core.identity import add_tenant_membership, get_membership
    from core.rbac import RoleScope, assign_role
    from product.agency.roles import ensure_client_member_role

    owner = make_user()
    member_user = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        member_role = ensure_client_member_role(client.tenant_id)
        membership = add_tenant_membership(client.tenant_id, member_user.id)
        owner_membership = get_membership(client.tenant_id, owner.id)
        assert owner_membership is None  # owner has no direct membership at the client
        assign_role(
            client.tenant_id,
            membership.id,
            member_role.id,
            scope=RoleScope.SELF,
            actor_user_id=owner.id,
        )

        contact = create_contact(
            member_user.id, client.tenant_id, first_name="M", last_name="Ember"
        )
        updated = update_contact(member_user.id, client.tenant_id, contact.id, first_name="Updated")
        assert updated.first_name == "Updated"

        with pytest.raises(CrmAccessDeniedError):
            delete_contact(member_user.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member_user.id)
