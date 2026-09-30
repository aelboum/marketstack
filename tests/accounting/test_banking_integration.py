"""`product/accounting/banking.py`: bank account metadata, CSV statement
import, duplicate-line detection, matching suggestion, reconciliation
(both confirm-to-document and assign-to-account), authorization, and
tenant isolation (docs/ROADMAP.md Phase 15.5). Real disposable Postgres.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from infra.db import select, tenant_session_scope
from product.accounting.accounts import create_account
from product.accounting.banking import (
    ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE,
    ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE,
    BankStatementLineView,
    assign_line_to_account,
    confirm_match_to_document,
    create_bank_account,
    get_bank_account,
    import_bank_statement_csv,
    list_bank_accounts,
    list_bank_statement_lines,
    suggest_matches,
)
from product.accounting.bills import BillLineInput, create_bill, post_bill
from product.accounting.contacts import tag_contact_role
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.invoices import InvoiceLineInput, create_invoice, get_invoice, post_invoice
from product.accounting.models import Payment, PaymentAllocation
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
    """Receivable + payable + revenue + bank-clearing accounts, an open
    period covering the test dates, one customer and one supplier
    contact."""
    receivable = create_account(
        owner_id, tenant_id, code="1100", name="Accounts Receivable", account_type="asset"
    )
    payable = create_account(
        owner_id, tenant_id, code="2000", name="Accounts Payable", account_type="liability"
    )
    revenue = create_account(owner_id, tenant_id, code="4000", name="Sales", account_type="revenue")
    expense = create_account(
        owner_id, tenant_id, code="5000", name="Office Expense", account_type="expense"
    )
    bank_ledger = create_account(
        owner_id, tenant_id, code="1000", name="Main Bank", account_type="asset"
    )
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    customer = create_contact(owner_id, tenant_id, first_name="Jane", last_name="Customer")
    tag_contact_role(owner_id, tenant_id, customer.id, role="customer")
    supplier = create_contact(owner_id, tenant_id, first_name="Acme", last_name="Supplies")
    tag_contact_role(owner_id, tenant_id, supplier.id, role="supplier")
    return receivable, payable, revenue, expense, bank_ledger, customer, supplier


def _posted_invoice(owner_id, tenant_id, receivable_id, revenue_id, contact_id, *, amount="121.00"):
    invoice = create_invoice(
        owner_id,
        tenant_id,
        contact_id=contact_id,
        receivable_account_id=receivable_id,
        currency="EUR",
        issue_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=[
            InvoiceLineInput(
                account_id=revenue_id,
                description="Consulting",
                quantity=Decimal("1"),
                unit_price=Decimal(amount),
            )
        ],
    )
    return post_invoice(owner_id, tenant_id, invoice.id)


def _posted_bill(owner_id, tenant_id, payable_id, expense_id, contact_id, *, amount="50.00"):
    bill = create_bill(
        owner_id,
        tenant_id,
        contact_id=contact_id,
        supplier_reference=_name("SUP"),
        payable_account_id=payable_id,
        currency="EUR",
        bill_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=[
            BillLineInput(
                account_id=expense_id,
                description="Supplies",
                quantity=Decimal("1"),
                unit_price=Decimal(amount),
            )
        ],
    )
    return post_bill(owner_id, tenant_id, bill.id)


def _bank_account(owner_id, tenant_id, ledger_account_id):
    return create_bank_account(
        owner_id, tenant_id, ledger_account_id=ledger_account_id, name="Main Bank", currency="EUR"
    )


_CSV_HEADER = "date,amount,description,reference"


def _csv(*rows: str) -> str:
    return "\n".join((_CSV_HEADER, *rows))


# --- Bank accounts (metadata only) --------------------------------------------------


def test_create_bank_account_requires_asset_ledger_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, _payable, revenue, _expense, _bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        with pytest.raises(AccountingValidationError):
            create_bank_account(
                owner.id,
                client.tenant_id,
                ledger_account_id=revenue.id,
                name="Main Bank",
                currency="EUR",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_bank_account_rejects_duplicate_ledger_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        with pytest.raises(AccountingValidationError):
            _bank_account(owner.id, client.tenant_id, bank_ledger.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_and_list_bank_accounts() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        created = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        fetched = get_bank_account(owner.id, client.tenant_id, created.id)
        assert fetched == created
        listed = list_bank_accounts(owner.id, client.tenant_id)
        assert [row.id for row in listed] == [created.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- CSV import / duplicate detection ------------------------------------------------


def test_import_bank_statement_csv_creates_lines() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received: list[str] = []
    subscribe(
        ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE, lambda event: received.append(event.type)
    )
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        csv_text = _csv(
            "2026-01-12,121.00,Invoice payment received,INV-1",
            "2026-01-13,-50.00,Office supplies,SUP-1",
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=csv_text,
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        assert statement.imported_line_count == 2
        assert statement.duplicate_line_count == 0
        assert len(statement.lines) == 2
        assert statement.lines[0].amount == Decimal("121.00")
        assert statement.lines[0].status == "unmatched"
        assert statement.lines[1].amount == Decimal("-50.00")
        assert received == [ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE]

        listed = list_bank_statement_lines(owner.id, client.tenant_id, statement.id)
        assert len(listed) == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reimporting_overlapping_csv_skips_duplicate_lines() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        first_csv = _csv(
            "2026-01-12,121.00,Invoice payment received,INV-1",
            "2026-01-13,-50.00,Office supplies,SUP-1",
        )
        first = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=first_csv,
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        assert first.imported_line_count == 2

        second_csv = _csv(
            "2026-01-13,-50.00,Office supplies,SUP-1",  # duplicate of row above
            "2026-01-20,200.00,Second payment,INV-2",
        )
        second = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=second_csv,
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        assert second.imported_line_count == 1
        assert second.duplicate_line_count == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_import_bank_statement_csv_rejects_wrong_header() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        with pytest.raises(AccountingValidationError):
            import_bank_statement_csv(
                owner.id,
                client.tenant_id,
                bank_account_id=bank_account.id,
                csv_text="wrong,header\n1,2",
                period_start_date=date(2026, 1, 1),
                period_end_date=date(2026, 1, 31),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Matching suggestion ---------------------------------------------------------------


def test_suggest_matches_ranks_by_amount_proximity() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, _payable, revenue, _expense, bank_ledger, customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        close_invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, customer.id, amount="120.00"
        )
        _far_invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, customer.id, amount="500.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-12,120.00,Invoice payment,REF"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]
        candidates = suggest_matches(owner.id, client.tenant_id, line.id)
        assert candidates[0].document_id == close_invoice.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Reconciliation: confirm match to document -----------------------------------------


def test_confirm_match_to_invoice_posts_payment_allocation_and_journal_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, _payable, revenue, _expense, bank_ledger, customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, customer.id, amount="121.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-12,121.00,Invoice payment received,INV-1"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]

        reconciled = confirm_match_to_document(
            owner.id,
            client.tenant_id,
            bank_statement_line_id=line.id,
            document_type="invoice",
            document_id=invoice.id,
        )
        assert reconciled.status == "reconciled"
        assert reconciled.matched_document_type == "invoice"
        assert reconciled.matched_document_id == invoice.id
        assert reconciled.matched_payment_id is not None
        assert reconciled.journal_entry_id is not None

        invoice_after = get_invoice(owner.id, client.tenant_id, invoice.id)
        assert invoice_after.outstanding_amount == Decimal("0.00")

        with pytest.raises(AccountingValidationError):
            confirm_match_to_document(
                owner.id,
                client.tenant_id,
                bank_statement_line_id=line.id,
                document_type="invoice",
                document_id=invoice.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_confirm_match_never_creates_orphan_payment() -> None:
    """Real concurrency, real Postgres: two threads race to confirm the
    *same* unmatched bank line against the same invoice at the same
    instant. Mirrors
    test_credit_notes_integration.py::test_concurrent_post_never_assigns_duplicate_credit_note_numbers()'s
    own `threading.Barrier`-based shape. Proves the row-lock fix: exactly
    one reconciliation succeeds (winner locks the line first via
    `with_for_update=True`), the loser observes `reconciled` and is
    rejected before ever creating a `Payment` -- never an orphan."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, _payable, revenue, _expense, bank_ledger, customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, customer.id, amount="121.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-12,121.00,Invoice payment received,INV-1"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line_id = statement.lines[0].id

        results: dict[str, BankStatementLineView] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _confirm(key: str) -> None:
            try:
                barrier.wait(timeout=5)
                results[key] = confirm_match_to_document(
                    owner.id,
                    client.tenant_id,
                    bank_statement_line_id=line_id,
                    document_type="invoice",
                    document_id=invoice.id,
                )
            except Exception as exc:  # noqa: BLE001 -- collected, asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=_confirm, args=("a",)),
            threading.Thread(target=_confirm, args=("b",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 1, f"expected exactly one winner, got: {results}"
        assert len(errors) == 1, f"expected exactly one rejected loser, got: {errors}"
        assert isinstance(errors[0], AccountingValidationError)

        winner = next(iter(results.values()))
        assert winner.status == "reconciled"
        assert winner.journal_entry_id is not None

        with tenant_session_scope(client.tenant_id) as session:
            payments = (
                session.execute(select(Payment).where(Payment.tenant_id == client.tenant_id))
                .scalars()
                .all()
            )
            allocations = (
                session.execute(
                    select(PaymentAllocation).where(
                        PaymentAllocation.tenant_id == client.tenant_id,
                        PaymentAllocation.document_id == invoice.id,
                    )
                )
                .scalars()
                .all()
            )
        assert len(payments) == 1, "loser must not create an orphan Payment"
        assert len(allocations) == 1

        invoice_after = get_invoice(owner.id, client.tenant_id, invoice.id)
        assert invoice_after.outstanding_amount == Decimal("0.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_confirm_match_to_bill_for_outflow_line() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, payable, _revenue, expense, bank_ledger, _customer, supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        bill = _posted_bill(
            owner.id, client.tenant_id, payable.id, expense.id, supplier.id, amount="50.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-13,-50.00,Office supplies,SUP-1"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]

        reconciled = confirm_match_to_document(
            owner.id,
            client.tenant_id,
            bank_statement_line_id=line.id,
            document_type="bill",
            document_id=bill.id,
        )
        assert reconciled.status == "reconciled"
        assert reconciled.matched_document_type == "bill"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_confirm_match_rejects_amount_mismatch() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, _payable, revenue, _expense, bank_ledger, customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, customer.id, amount="121.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-12,100.00,Partial payment,INV-1"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]
        with pytest.raises(AccountingValidationError):
            confirm_match_to_document(
                owner.id,
                client.tenant_id,
                bank_statement_line_id=line.id,
                document_type="invoice",
                document_id=invoice.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_confirm_match_rejects_wrong_document_type_for_direction() -> None:
    """An inflow line may only match an invoice, never a bill."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _receivable, payable, _revenue, expense, bank_ledger, _customer, supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        bill = _posted_bill(
            owner.id, client.tenant_id, payable.id, expense.id, supplier.id, amount="50.00"
        )
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-13,50.00,Mismatched inflow,SUP-1"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]
        with pytest.raises(AccountingValidationError):
            confirm_match_to_document(
                owner.id,
                client.tenant_id,
                bank_statement_line_id=line.id,
                document_type="bill",
                document_id=bill.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Reconciliation: assign to account (no matching document) ---------------------------


def test_assign_line_to_account_posts_direct_journal_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received: list[str] = []
    subscribe(ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE, lambda event: received.append(event.type))
    try:
        _receivable, _payable, _revenue, expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        bank_account = _bank_account(owner.id, client.tenant_id, bank_ledger.id)
        statement = import_bank_statement_csv(
            owner.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-14,-12.50,Bank fee,"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        line = statement.lines[0]

        reconciled = assign_line_to_account(
            owner.id,
            client.tenant_id,
            bank_statement_line_id=line.id,
            account_id=expense.id,
        )
        assert reconciled.status == "reconciled"
        assert reconciled.matched_account_id == expense.id
        assert reconciled.journal_entry_id is not None
        assert received == [ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Authorization / tenant isolation ----------------------------------------------------


def test_unrelated_actor_cannot_create_bank_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        _receivable, _payable, _revenue, _expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        with pytest.raises(AccountingAccessDeniedError):
            create_bank_account(
                unrelated.id,
                client.tenant_id,
                ledger_account_id=bank_ledger.id,
                name="Main Bank",
                currency="EUR",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_import_and_reconcile() -> None:
    """`BANKING_RESOURCE` has no higher-risk action withheld from `member`
    (`product/accounting/permissions.py`'s own module docstring)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    try:
        _receivable, _payable, _revenue, expense, bank_ledger, _customer, _supplier = _setup(
            owner.id, client.tenant_id
        )
        _add_member(owner.id, client.tenant_id, member.id)
        bank_account = _bank_account(member.id, client.tenant_id, bank_ledger.id)
        statement = import_bank_statement_csv(
            member.id,
            client.tenant_id,
            bank_account_id=bank_account.id,
            csv_text=_csv("2026-01-14,-12.50,Bank fee,"),
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 1, 31),
        )
        reconciled = assign_line_to_account(
            member.id,
            client.tenant_id,
            bank_statement_line_id=statement.lines[0].id,
            account_id=expense.id,
        )
        assert reconciled.status == "reconciled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_bank_accounts_are_isolated_across_tenants() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        _receivable_a, _payable_a, _revenue_a, _expense_a, bank_ledger_a, _c_a, _s_a = _setup(
            owner_a.id, client_a.tenant_id
        )
        bank_account_a = _bank_account(owner_a.id, client_a.tenant_id, bank_ledger_a.id)

        _setup(owner_b.id, client_b.tenant_id)
        with pytest.raises(AccountingReferenceNotFoundError):
            get_bank_account(owner_b.id, client_b.tenant_id, bank_account_a.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
