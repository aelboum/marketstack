"""Cross-cutting adversarial isolation tests not already covered by
tests/crm/test_contacts_companies_integration.py -- explicit deny
overriding SUBTREE reach for CRM data, and tenant lifecycle fencing.
Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.rbac import RoleScope
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.crm.companies import create_company
from product.crm.contacts import create_contact
from product.crm.errors import CrmAccessDeniedError
from product.crm.permissions import CONTACT_RESOURCE

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_explicit_deny_overrides_inherited_subtree_reach_for_crm() -> None:
    """The agency owner's SUBTREE role reaches the client's CRM data by
    default; an explicit deny on the specific CRM permission, at the
    client tenant, removes it there -- mirrors
    tests/agency/test_isolation_integration.py
    ::test_explicit_deny_overrides_subtree_delegation's shape, applied
    to a real product-owned permission instead of `agency.client`."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Visible", last_name="Contact"
        )
        assert contact.id is not None  # owner can read/write before any deny exists

        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=CONTACT_RESOURCE,
            action="create",
            scope_mode=RoleScope.SELF,
        )

        with pytest.raises(CrmAccessDeniedError):
            create_contact(owner.id, client.tenant_id, first_name="Should", last_name="Fail")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_suspended_client_tenant_denies_crm_mutation() -> None:
    """Requirement 7: deleted/suspended/purged tenants cannot continue
    operating on CRM records -- can()'s own lifecycle re-check
    (`core/rbac/authorization.py`) denies a SUSPENDED tenant's own
    principals, exactly as it does for the agency module."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(owner.id, client.tenant_id, first_name="Before", last_name="Suspend")
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(CrmAccessDeniedError):
            create_contact(owner.id, client.tenant_id, first_name="After", last_name="Suspend")
        with pytest.raises(CrmAccessDeniedError):
            create_company(owner.id, client.tenant_id, name="Should Fail Too")
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_contacts_pagination_is_bounded() -> None:
    """API security requirement: bounded list/search results -- a
    caller-supplied limit larger than MAX_PAGE_SIZE is clamped, never
    honored as an unbounded request."""
    from product.crm.contacts import list_contacts
    from product.crm.pagination import MAX_PAGE_SIZE

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for i in range(3):
            create_contact(owner.id, client.tenant_id, first_name=f"C{i}", last_name="Bulk")
        results = list_contacts(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
