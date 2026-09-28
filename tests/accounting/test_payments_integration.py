"""`product/accounting/payments.py`: payments, allocations, dual locking,
reversal, idempotency, authorization, and events (docs/ROADMAP.md Phase
25, ADR-0014 Decision 8 + its own Phase 25 reconciliation addendum). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.accounting.accounts import create_account
from product.accounting.bills import BillLineInput, create_bill, post_bill
from product.accounting.contacts import tag_contact_role
from product.accounting.errors import AccountingAccessDeniedError, AccountingValidationError
from product.accounting.invoices import InvoiceLineInput, create_invoice, post_invoice
from product.accounting.payments import (
    ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE,
    ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE,
    create_allocation,
    create_payment,
    get_payment,
    list_allocations_for_document,
    reverse_allocation,
)
from product.accounting.periods import create_period
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
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _setup(owner_id, tenant_id):
    receivable = create_account(
        owner_id, tenant_id, code="1100", name="Accounts Receivable", account_type="asset"
    )
    revenue = create_account(owner_id, tenant_id, code="4000", name="Sales", account_type="revenue")
    payable = create_account(
        owner_id, tenant_id, code="2000", name="Accounts Payable", account_type="liability"
    )
    expense = create_account(owner_id, tenant_id, code="6000", name="Costs", account_type="expense")
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    customer = create_contact(owner_id, tenant_id, first_name="Jane", last_name="Customer")
    tag_contact_role(owner_id, tenant_id, customer.id, role="customer")
    supplier = create_contact(owner_id, tenant_id, first_name="Acme", last_name="Supplies")
    tag_contact_role(owner_id, tenant_id, supplier.id, role="supplier")
    return receivable, revenue, payable, expense, customer, supplier


def _post_invoice(owner_id, tenant_id, receivable, revenue, customer, amount: Decimal, ref: str):
    invoice = create_invoice(
        owner_id,
        tenant_id,
        contact_id=customer.id,
        receivable_account_id=receivable.id,
        currency="EUR",
        issue_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=[
            InvoiceLineInput(
                account_id=revenue.id, description=ref, quantity=Decimal("1"), unit_price=amount
            )
        ],
    )
    return post_invoice(owner_id, tenant_id, invoice.id)


def _post_bill(owner_id, tenant_id, payable, expense, supplier, amount: Decimal, ref: str):
    bill = create_bill(
        owner_id,
        tenant_id,
        contact_id=supplier.id,
        supplier_reference=ref,
        payable_account_id=payable.id,
        currency="EUR",
        bill_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=[
            BillLineInput(
                account_id=expense.id, description=ref, quantity=Decimal("1"), unit_price=amount
            )
        ],
    )
    return post_bill(owner_id, tenant_id, bill.id)


# --- Payment creation ----------------------------------------------------------


def test_create_payment_inbound_requires_customer_role() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _r, _rev, _p, _e, customer, supplier = _setup(owner.id, client.tenant_id)
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="eur",
        )
        assert payment.currency == "EUR"
        assert payment.unallocated_amount == Decimal("100.00")

        with pytest.raises(AccountingValidationError):
            create_payment(
                owner.id,
                client.tenant_id,
                contact_id=supplier.id,
                direction="inbound",
                amount=Decimal("50.00"),
                currency="EUR",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_payment_rejects_non_positive_amount() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _r, _rev, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_payment(
                owner.id,
                client.tenant_id,
                contact_id=customer.id,
                direction="inbound",
                amount=Decimal("0"),
                currency="EUR",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Allocation ------------------------------------------------------------


def test_create_allocation_reduces_both_sides_and_marks_fully_allocated() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-A"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        allocation = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        assert allocation.amount == Decimal("100.00")

        updated_payment = get_payment(owner.id, client.tenant_id, payment.id)
        assert updated_payment.unallocated_amount == Decimal("0")
        assert updated_payment.is_fully_allocated is True

        from product.accounting.invoices import get_invoice

        updated_invoice = get_invoice(owner.id, client.tenant_id, invoice.id)
        assert updated_invoice.outstanding_amount == Decimal("0")

        allocations = list_allocations_for_document(
            owner.id, client.tenant_id, document_type="invoice", document_id=invoice.id
        )
        assert len(allocations) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_allocation_can_partially_cover_a_document() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _r, _rev, payable, expense, _customer, supplier = _setup(owner.id, client.tenant_id)
        bill = _post_bill(
            owner.id, client.tenant_id, payable, expense, supplier, Decimal("100.00"), "BILL-A"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=supplier.id,
            direction="outbound",
            amount=Decimal("40.00"),
            currency="EUR",
        )
        create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="bill",
            document_id=bill.id,
            amount=Decimal("40.00"),
        )
        from product.accounting.bills import get_bill

        updated_bill = get_bill(owner.id, client.tenant_id, bill.id)
        assert updated_bill.outstanding_amount == Decimal("60.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_allocation_rejects_amount_exceeding_unallocated_payment() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-B"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("30.00"),
            currency="EUR",
        )
        with pytest.raises(AccountingValidationError):
            create_allocation(
                owner.id,
                client.tenant_id,
                payment_id=payment.id,
                document_type="invoice",
                document_id=invoice.id,
                amount=Decimal("50.00"),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_allocation_rejects_amount_exceeding_document_outstanding() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("30.00"), "INV-C"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        with pytest.raises(AccountingValidationError):
            create_allocation(
                owner.id,
                client.tenant_id,
                payment_id=payment.id,
                document_type="invoice",
                document_id=invoice.id,
                amount=Decimal("50.00"),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_allocation_rejects_non_posted_document() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        draft_invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=[
                InvoiceLineInput(
                    account_id=revenue.id,
                    description="x",
                    quantity=Decimal("1"),
                    unit_price=Decimal("10.00"),
                )
            ],
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("10.00"),
            currency="EUR",
        )
        with pytest.raises(AccountingValidationError):
            create_allocation(
                owner.id,
                client.tenant_id,
                payment_id=payment.id,
                document_type="invoice",
                document_id=draft_invoice.id,
                amount=Decimal("10.00"),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Reversal ------------------------------------------------------------------


def test_reverse_allocation_restores_both_sides() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-D"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        allocation = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        reversal = reverse_allocation(owner.id, client.tenant_id, allocation.id)
        assert reversal.reverses_allocation_id == allocation.id
        assert reversal.amount == Decimal("100.00")

        restored_payment = get_payment(owner.id, client.tenant_id, payment.id)
        assert restored_payment.unallocated_amount == Decimal("100.00")

        from product.accounting.invoices import get_invoice

        restored_invoice = get_invoice(owner.id, client.tenant_id, invoice.id)
        assert restored_invoice.outstanding_amount == Decimal("100.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_allocation_twice_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-E"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        allocation = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        reverse_allocation(owner.id, client.tenant_id, allocation.id)
        with pytest.raises(AccountingValidationError):
            reverse_allocation(owner.id, client.tenant_id, allocation.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_of_a_reversal_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-F"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        allocation = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        reversal = reverse_allocation(owner.id, client.tenant_id, allocation.id)
        with pytest.raises(AccountingValidationError):
            reverse_allocation(owner.id, client.tenant_id, reversal.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_allocation_is_owner_only() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            member.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-G"
        )
        payment = create_payment(
            member.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        allocation = create_allocation(
            member.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        with pytest.raises(AccountingAccessDeniedError):
            reverse_allocation(member.id, client.tenant_id, allocation.id)
        reversal = reverse_allocation(owner.id, client.tenant_id, allocation.id)
        assert reversal.reverses_allocation_id == allocation.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Idempotency, events -------------------------------------------------------


def test_repeated_allocate_with_same_idempotency_key_does_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-H"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        key = f"allocate-{uuid.uuid4()}"
        first = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
            idempotency_key=key,
        )
        second = create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
            idempotency_key=key,
        )
        assert first.id == second.id
        allocations = list_allocations_for_document(
            owner.id, client.tenant_id, document_type="invoice", document_id=invoice.id
        )
        assert len(allocations) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_payment_and_allocate_publish_expected_events() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received_types: list[str] = []

    def _handler(event) -> None:
        received_types.append(event.type)

    subscribe(ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE, _handler)
    subscribe(ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE, _handler)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("100.00"), "INV-I"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )
        create_allocation(
            owner.id,
            client.tenant_id,
            payment_id=payment.id,
            document_type="invoice",
            document_id=invoice.id,
            amount=Decimal("100.00"),
        )
        assert received_types == [
            ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE,
            ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE,
        ]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Concurrency: dual locking prevents a lost update on the payment side ------


def test_concurrent_allocations_from_same_payment_never_lose_an_update() -> None:
    """Real concurrency, real Postgres: one payment, two different
    invoices, two threads allocating from the *same* payment against
    *different* documents at the same instant -- exactly the race the
    module docstring's own dual-lock correction targets (the original
    Decision 8 locked only the document, missing this one). Both
    allocations must succeed and `payment.unallocated_amount` must reflect
    both deductions -- never a lost update from an unlocked read-modify-
    write on the payment row. Mirrors
    `test_invoices_integration.py::test_concurrent_post_never_assigns_duplicate_numbers`'s
    own `threading.Barrier`-based shape."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        invoice_a = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("60.00"), "INV-J"
        )
        invoice_b = _post_invoice(
            owner.id, client.tenant_id, receivable, revenue, customer, Decimal("40.00"), "INV-K"
        )
        payment = create_payment(
            owner.id,
            client.tenant_id,
            contact_id=customer.id,
            direction="inbound",
            amount=Decimal("100.00"),
            currency="EUR",
        )

        results: dict[str, object] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _allocate(key: str, invoice_id: uuid.UUID, amount: Decimal) -> None:
            try:
                barrier.wait(timeout=5)
                results[key] = create_allocation(
                    owner.id,
                    client.tenant_id,
                    payment_id=payment.id,
                    document_type="invoice",
                    document_id=invoice_id,
                    amount=amount,
                )
            except Exception as exc:  # noqa: BLE001 -- collected, asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=_allocate, args=("a", invoice_a.id, Decimal("60.00"))),
            threading.Thread(target=_allocate, args=("b", invoice_b.id, Decimal("40.00"))),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        assert "a" in results and "b" in results

        final_payment = get_payment(owner.id, client.tenant_id, payment.id)
        assert final_payment.unallocated_amount == Decimal("0")
        assert final_payment.is_fully_allocated is True
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Authorization ---------------------------------------------------------


def test_unrelated_actor_cannot_create_payment() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _r, _rev, _p, _e, customer, _supplier = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            create_payment(
                outsider.id,
                client.tenant_id,
                contact_id=customer.id,
                direction="inbound",
                amount=Decimal("10.00"),
                currency="EUR",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)
