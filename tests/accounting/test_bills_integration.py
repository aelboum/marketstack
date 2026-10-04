"""`product/accounting/bills.py`: supplier bill lifecycle, tax
calculation, atomic journal posting (input VAT, debit side), owner-only
posting (ADR-0014 Decision 13's own asymmetry with invoices), duplicate
supplier-reference detection, idempotency, authorization, and events
(docs/ROADMAP.md Phase 25, ADR-0014 Decisions 6, 7, 12, 13). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.accounting.accounts import create_account
from product.accounting.bills import (
    ACCOUNTING_BILL_CREATED_EVENT_TYPE,
    ACCOUNTING_BILL_POSTED_EVENT_TYPE,
    BillLineInput,
    cancel_bill,
    create_bill,
    get_bill,
    post_bill,
    update_bill,
    void_bill,
)
from product.accounting.contacts import tag_contact_role
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.periods import create_period
from product.accounting.tax_codes import create_tax_code
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.contacts import create_contact
from product.foundation.events import subscribe

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


def _setup(owner_id, tenant_id):
    payable = create_account(
        owner_id, tenant_id, code="2000", name="Accounts Payable", account_type="liability"
    )
    expense = create_account(
        owner_id, tenant_id, code="6000", name="Office Costs", account_type="expense"
    )
    tax_account = create_account(
        owner_id, tenant_id, code="1400", name="VAT Receivable", account_type="asset"
    )
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    contact = create_contact(owner_id, tenant_id, first_name="Acme", last_name="Supplies")
    tag_contact_role(owner_id, tenant_id, contact.id, role="supplier")
    tax_code = create_tax_code(
        owner_id,
        tenant_id,
        code="NL-STD",
        name="Standard VAT",
        rate_percent=Decimal("21.0"),
        tax_type="purchase",
        tax_account_id=tax_account.id,
    )
    return payable, expense, tax_account, contact, tax_code


def _lines(expense_id, tax_code_id=None):
    return [
        BillLineInput(
            account_id=expense_id,
            description="Office supplies",
            quantity=Decimal("1"),
            unit_price=Decimal("50.00"),
            tax_code_id=tax_code_id,
        )
    ]


# --- Creation / tax calculation ------------------------------------------------


def test_create_bill_computes_tax_and_totals() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0001",
            payable_account_id=payable.id,
            currency="eur",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        assert bill.status == "draft"
        assert bill.currency == "EUR"
        assert bill.subtotal == Decimal("50.00")
        assert bill.tax_total == Decimal("10.50")
        assert bill.total == Decimal("60.50")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_bill_rejects_duplicate_supplier_reference() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, _tax_code = _setup(owner.id, client.tenant_id)
        create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0001",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id),
        )
        with pytest.raises(AccountingConflictError):
            create_bill(
                owner.id,
                client.tenant_id,
                contact_id=contact.id,
                supplier_reference="INV-0001",
                payable_account_id=payable.id,
                currency="EUR",
                bill_date=date(2026, 2, 1),
                due_date=date(2026, 2, 15),
                lines=_lines(expense.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_bill_requires_supplier_or_both_role() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, _contact, _tax_code = _setup(owner.id, client.tenant_id)
        customer_only = create_contact(
            owner.id, client.tenant_id, first_name="Cus", last_name="Tomer"
        )
        tag_contact_role(owner.id, client.tenant_id, customer_only.id, role="customer")
        with pytest.raises(AccountingValidationError):
            create_bill(
                owner.id,
                client.tenant_id,
                contact_id=customer_only.id,
                supplier_reference="INV-0002",
                payable_account_id=payable.id,
                currency="EUR",
                bill_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(expense.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_bill_rejects_due_before_bill_date() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, _tax_code = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_bill(
                owner.id,
                client.tenant_id,
                contact_id=contact.id,
                supplier_reference="INV-0003",
                payable_account_id=payable.id,
                currency="EUR",
                bill_date=date(2026, 1, 10),
                due_date=date(2026, 1, 1),
                lines=_lines(expense.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Update / void (draft-only) ------------------------------------------------


def test_update_and_void_draft_bill() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0004",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        updated = update_bill(
            owner.id, client.tenant_id, bill.id, description="Corrected", lines=_lines(expense.id)
        )
        assert updated.description == "Corrected"
        assert updated.tax_total == Decimal("0")

        voided = void_bill(owner.id, client.tenant_id, bill.id)
        assert voided.status == "voided"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Posting: owner-only, journal balance --------------------------------------


def test_post_bill_creates_balanced_journal_entry_debit_side() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0005",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        posted = post_bill(owner.id, client.tenant_id, bill.id)
        assert posted.status == "posted"
        assert posted.outstanding_amount == Decimal("60.50")

        from product.accounting.journal import get_journal_entry

        assert posted.journal_entry_id is not None
        entry = get_journal_entry(owner.id, client.tenant_id, posted.journal_entry_id)
        total_debits = sum((line.debit_amount for line in entry.lines), Decimal("0"))
        total_credits = sum((line.credit_amount for line in entry.lines), Decimal("0"))
        assert total_debits == total_credits == Decimal("60.50")
        payable_line = next(line for line in entry.lines if line.account_id == payable.id)
        assert payable_line.credit_amount == Decimal("60.50")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_bill_is_owner_only() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            member.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0006",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        with pytest.raises(AccountingAccessDeniedError):
            post_bill(member.id, client.tenant_id, bill.id)
        posted = post_bill(owner.id, client.tenant_id, bill.id)
        assert posted.status == "posted"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_post_already_posted_bill_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0007",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        post_bill(owner.id, client.tenant_id, bill.id)
        with pytest.raises(AccountingValidationError):
            post_bill(owner.id, client.tenant_id, bill.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Cancellation --------------------------------------------------------------


def test_cancel_posted_bill_reverses_journal_and_zeroes_outstanding() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0008",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        posted = post_bill(owner.id, client.tenant_id, bill.id)
        cancelled = cancel_bill(owner.id, client.tenant_id, posted.id)
        assert cancelled.status == "cancelled"
        assert cancelled.outstanding_amount == Decimal("0")

        from product.accounting.journal import get_journal_entry

        assert posted.journal_entry_id is not None
        original_entry = get_journal_entry(owner.id, client.tenant_id, posted.journal_entry_id)
        assert original_entry.status == "reversed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Idempotency -----------------------------------------------------------


def test_repeated_post_with_same_idempotency_key_does_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0009",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        key = f"post-{uuid.uuid4()}"
        first = post_bill(owner.id, client.tenant_id, bill.id, idempotency_key=key)
        second = post_bill(owner.id, client.tenant_id, bill.id, idempotency_key=key)
        assert first.journal_entry_id == second.journal_entry_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Events ------------------------------------------------------------------


def test_create_and_post_publish_expected_events() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received_types: list[str] = []

    def _handler(event) -> None:
        received_types.append(event.type)

    subscribe(ACCOUNTING_BILL_CREATED_EVENT_TYPE, _handler)
    subscribe(ACCOUNTING_BILL_POSTED_EVENT_TYPE, _handler)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        bill = create_bill(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0010",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        post_bill(owner.id, client.tenant_id, bill.id)
        assert received_types == [
            ACCOUNTING_BILL_CREATED_EVENT_TYPE,
            ACCOUNTING_BILL_POSTED_EVENT_TYPE,
        ]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation / authorization ------------------------------------------


def test_bills_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client_a.tenant_id)
        bill = create_bill(
            owner.id,
            client_a.tenant_id,
            contact_id=contact.id,
            supplier_reference="INV-0011",
            payable_account_id=payable.id,
            currency="EUR",
            bill_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(expense.id, tax_code.id),
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_bill(owner.id, client_b.tenant_id, bill.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_bill() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        payable, expense, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            create_bill(
                outsider.id,
                client.tenant_id,
                contact_id=contact.id,
                supplier_reference="INV-0012",
                payable_account_id=payable.id,
                currency="EUR",
                bill_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(expense.id, tax_code.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)
