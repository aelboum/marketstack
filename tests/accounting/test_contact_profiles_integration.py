"""`product/accounting/contacts.py`: customer/supplier role-tagging on
existing `crm.contacts` rows (docs/ROADMAP.md Phase 25, ADR-0014 Decision
6 + its own addendum). Real disposable Postgres. Marked `integration`,
excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from infra.db import IntegrityError
from product.accounting.contacts import (
    get_contact_role,
    list_contact_roles,
    tag_contact_role,
    update_contact_role,
)
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.contacts import create_contact, delete_contact
from product.crm.errors import CrmReferenceNotFoundError

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(
        tenant_id, user_id, caller=SystemCaller(SystemAuthority.PROVISIONING)
    )
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, caller=UserCaller(owner_id)
    )


def _make_contact(owner_id, tenant_id):
    return create_contact(owner_id, tenant_id, first_name="Jane", last_name="Doe")


def test_tag_get_update_list_contact_role() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        tagged = tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        assert tagged.contact_id == contact.id
        assert tagged.role == "customer"

        fetched = get_contact_role(owner.id, client.tenant_id, contact.id)
        assert fetched.id == tagged.id

        updated = update_contact_role(owner.id, client.tenant_id, contact.id, role="both")
        assert updated.role == "both"

        rows = list_contact_roles(owner.id, client.tenant_id)
        assert any(r.contact_id == contact.id for r in rows)

        customers_only = list_contact_roles(owner.id, client.tenant_id, role="both")
        assert all(r.role == "both" for r in customers_only)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tag_contact_role_rejects_invalid_role() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            tag_contact_role(owner.id, client.tenant_id, contact.id, role="vendor")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tag_contact_role_rejects_unknown_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(CrmReferenceNotFoundError):
            tag_contact_role(owner.id, client.tenant_id, uuid.uuid4(), role="customer")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tag_same_contact_twice_conflicts() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        with pytest.raises(AccountingConflictError):
            tag_contact_role(owner.id, client.tenant_id, contact.id, role="supplier")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_untagged_contact_role_not_found() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        with pytest.raises(AccountingReferenceNotFoundError):
            get_contact_role(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_contact_profiles_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client_a.tenant_id)
        tag_contact_role(owner.id, client_a.tenant_id, contact.id, role="customer")
        with pytest.raises(AccountingReferenceNotFoundError):
            get_contact_role(owner.id, client_b.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_tag_or_update() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            tag_contact_role(outsider.id, client.tenant_id, contact.id, role="customer")
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        with pytest.raises(AccountingAccessDeniedError):
            update_contact_role(outsider.id, client.tenant_id, contact.id, role="supplier")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_member_can_tag_and_read_contact_role() -> None:
    """ADR-0014 Decision 6 carries no owner-only asymmetry -- ordinary
    day-to-day bookkeeping, mirrors `INVOICE_RESOURCE.create`/`.read`
    being granted to `member` too."""
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        contact = _make_contact(owner.id, client.tenant_id)
        tagged = tag_contact_role(member.id, client.tenant_id, contact.id, role="customer")
        fetched = get_contact_role(member.id, client.tenant_id, contact.id)
        assert fetched.id == tagged.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_deleting_a_tagged_contact_fails_with_integrity_error() -> None:
    """ADR-0014 Decision 6 addendum's own disclosed, accepted trade-off --
    `contact_profiles.contact_id` carries no `ON DELETE` clause (default
    `RESTRICT`), so `product.crm.contacts.delete_contact()` fails with a
    raw, untranslated `IntegrityError` once a contact is tagged.
    `product/crm/` is not modified to add a friendlier error."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _make_contact(owner.id, client.tenant_id)
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        with pytest.raises(IntegrityError):
            delete_contact(owner.id, client.tenant_id, contact.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
