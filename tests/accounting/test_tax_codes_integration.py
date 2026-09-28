"""`product/accounting/tax_codes.py`: tenant-owned tax-rate catalog
(docs/ROADMAP.md Phase 25, ADR-0014 Decision 7). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from product.accounting.accounts import create_account
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.tax_codes import (
    create_tax_code,
    deactivate_tax_code,
    get_tax_code,
    list_tax_codes,
)
from product.agency.provisioning import provision_agency, provision_client

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _tax_account(owner_id, tenant_id):
    return create_account(
        owner_id, tenant_id, code="2200", name="VAT Payable", account_type="liability"
    )


def test_create_get_list_deactivate_tax_code() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client.tenant_id)
        code = create_tax_code(
            owner.id,
            client.tenant_id,
            code="NL-STD",
            name="Standard VAT",
            rate_percent=Decimal("21.0"),
            tax_type="sales",
            tax_account_id=account.id,
        )
        assert code.is_active is True
        assert code.rate_percent == Decimal("21.0")

        fetched = get_tax_code(owner.id, client.tenant_id, code.id)
        assert fetched.id == code.id

        rows = list_tax_codes(owner.id, client.tenant_id)
        assert any(r.id == code.id for r in rows)

        deactivated = deactivate_tax_code(owner.id, client.tenant_id, code.id)
        assert deactivated.is_active is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_tax_code_rejects_duplicate_code() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client.tenant_id)
        create_tax_code(
            owner.id,
            client.tenant_id,
            code="NL-STD",
            name="Standard VAT",
            rate_percent=Decimal("21.0"),
            tax_type="sales",
            tax_account_id=account.id,
        )
        with pytest.raises(AccountingConflictError):
            create_tax_code(
                owner.id,
                client.tenant_id,
                code="NL-STD",
                name="Duplicate",
                rate_percent=Decimal("9.0"),
                tax_type="sales",
                tax_account_id=account.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_tax_code_rejects_unknown_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingReferenceNotFoundError):
            create_tax_code(
                owner.id,
                client.tenant_id,
                code="NL-STD",
                name="Standard VAT",
                rate_percent=Decimal("21.0"),
                tax_type="sales",
                tax_account_id=uuid.uuid4(),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_tax_code_rejects_invalid_type_and_negative_rate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_tax_code(
                owner.id,
                client.tenant_id,
                code="NL-STD",
                name="Standard VAT",
                rate_percent=Decimal("21.0"),
                tax_type="import",
                tax_account_id=account.id,
            )
        with pytest.raises(AccountingValidationError):
            create_tax_code(
                owner.id,
                client.tenant_id,
                code="NL-NEG",
                name="Negative",
                rate_percent=Decimal("-1"),
                tax_type="sales",
                tax_account_id=account.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_tax_code_rejects_effective_to_before_from() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_tax_code(
                owner.id,
                client.tenant_id,
                code="NL-STD",
                name="Standard VAT",
                rate_percent=Decimal("21.0"),
                tax_type="sales",
                tax_account_id=account.id,
                effective_from=date(2026, 6, 1),
                effective_to=date(2026, 1, 1),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tax_codes_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client_a.tenant_id)
        code = create_tax_code(
            owner.id,
            client_a.tenant_id,
            code="NL-STD",
            name="Standard VAT",
            rate_percent=Decimal("21.0"),
            tax_type="sales",
            tax_account_id=account.id,
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_tax_code(owner.id, client_b.tenant_id, code.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_or_deactivate_tax_code() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        account = _tax_account(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            create_tax_code(
                outsider.id,
                client.tenant_id,
                code="NL-STD",
                name="Standard VAT",
                rate_percent=Decimal("21.0"),
                tax_type="sales",
                tax_account_id=account.id,
            )
        code = create_tax_code(
            owner.id,
            client.tenant_id,
            code="NL-STD",
            name="Standard VAT",
            rate_percent=Decimal("21.0"),
            tax_type="sales",
            tax_account_id=account.id,
        )
        with pytest.raises(AccountingAccessDeniedError):
            deactivate_tax_code(outsider.id, client.tenant_id, code.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)
