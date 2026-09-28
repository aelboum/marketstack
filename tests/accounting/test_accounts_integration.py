"""`product/accounting/accounts.py`: chart-of-accounts CRUD, tenant
isolation, authorization, and the per-tenant `code` uniqueness invariant
(docs/ROADMAP.md Phase 24). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.accounting.accounts import (
    create_account,
    deactivate_account,
    get_account,
    list_accounts,
    reactivate_account,
    update_account,
)
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def test_create_get_list_update_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        assert created.code == "1000"
        assert created.account_type == "asset"
        assert created.is_active is True

        fetched = get_account(owner.id, client.tenant_id, created.id)
        assert fetched == created

        updated = update_account(owner.id, client.tenant_id, created.id, name="Petty Cash")
        assert updated.name == "Petty Cash"
        assert updated.code == "1000"  # code is immutable after creation

        rows = list_accounts(owner.id, client.tenant_id)
        assert [r.id for r in rows] == [created.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_account_rejects_unknown_account_type() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingValidationError):
            create_account(
                owner.id, client.tenant_id, code="1000", name="Cash", account_type="crypto"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_duplicate_account_code_same_tenant_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_account(owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset")
        with pytest.raises(AccountingConflictError):
            create_account(
                owner.id, client.tenant_id, code="1000", name="Cash 2", account_type="asset"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_same_account_code_allowed_across_different_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        a = create_account(
            owner.id, client_a.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        b = create_account(
            owner.id, client_b.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        assert a.tenant_id != b.tenant_id
        assert a.code == b.code == "1000"
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_get_unknown_account_is_non_enumerating_not_found() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingReferenceNotFoundError):
            get_account(owner.id, client.tenant_id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_accounts_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        account = create_account(
            owner.id, client_a.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_account(owner.id, client_b.tenant_id, account.id)
        assert list_accounts(owner.id, client_b.tenant_id) == []
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_account() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingAccessDeniedError):
            create_account(
                outsider.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_member_can_create_and_update_account() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        account = create_account(
            member.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        updated = update_account(member.id, client.tenant_id, account.id, name="Renamed")
        assert updated.name == "Renamed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_deactivate_and_reactivate_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        deactivated = deactivate_account(owner.id, client.tenant_id, account.id)
        assert deactivated.is_active is False
        reactivated = reactivate_account(owner.id, client.tenant_id, account.id)
        assert reactivated.is_active is True
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_suspended_tenant_denies_account_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED, actor_user_id=owner.id)
        with pytest.raises(AccountingAccessDeniedError):
            create_account(
                owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
            )
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE, actor_user_id=owner.id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_accounts_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for i in range(3):
            create_account(
                owner.id, client.tenant_id, code=f"1{i:03d}", name=f"Acct {i}", account_type="asset"
            )
        rows = list_accounts(owner.id, client.tenant_id, limit=2)
        assert len(rows) == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
