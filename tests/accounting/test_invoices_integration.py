"""`product/accounting/invoices.py`: customer invoice lifecycle, tax
calculation, gapless numbering, atomic journal posting, cancellation,
idempotency, authorization, and events (docs/ROADMAP.md Phase 25,
ADR-0014 Decisions 6, 7, 12, 13). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.audit_log import list as list_audit_log
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from product.accounting.accounts import create_account
from product.accounting.contacts import tag_contact_role
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingPeriodNotFoundError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.invoices import (
    ACCOUNTING_INVOICE_CREATED_EVENT_TYPE,
    ACCOUNTING_INVOICE_POSTED_EVENT_TYPE,
    InvoiceLineInput,
    InvoiceView,
    cancel_invoice,
    create_invoice,
    get_invoice,
    list_invoices,
    post_invoice,
    update_invoice,
    void_invoice,
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
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _setup(owner_id, tenant_id):
    """Receivable + revenue + tax accounts, a covering open period, a
    tagged customer contact, and one 21% sales tax code -- the common
    fixture every test below builds on."""
    receivable = create_account(
        owner_id, tenant_id, code="1100", name="Accounts Receivable", account_type="asset"
    )
    revenue = create_account(owner_id, tenant_id, code="4000", name="Sales", account_type="revenue")
    tax_account = create_account(
        owner_id, tenant_id, code="2200", name="VAT Payable", account_type="liability"
    )
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    contact = create_contact(owner_id, tenant_id, first_name="Jane", last_name="Customer")
    tag_contact_role(owner_id, tenant_id, contact.id, role="customer")
    tax_code = create_tax_code(
        owner_id,
        tenant_id,
        code="NL-STD",
        name="Standard VAT",
        rate_percent=Decimal("21.0"),
        tax_type="sales",
        tax_account_id=tax_account.id,
    )
    return receivable, revenue, tax_account, contact, tax_code


def _lines(revenue_id, tax_code_id=None):
    return [
        InvoiceLineInput(
            account_id=revenue_id,
            description="Consulting",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            tax_code_id=tax_code_id,
        )
    ]


# --- Creation / tax calculation ----------------------------------------------


def test_create_invoice_computes_tax_and_totals() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="eur",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        assert invoice.status == "draft"
        assert invoice.invoice_number is None
        assert invoice.currency == "EUR"
        assert invoice.subtotal == Decimal("200.00")
        assert invoice.tax_total == Decimal("42.00")
        assert invoice.total == Decimal("242.00")
        assert invoice.outstanding_amount == Decimal("0")  # not yet posted
        assert len(invoice.lines) == 1
        assert invoice.lines[0].line_tax == Decimal("42.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_invoice_untaxed_line_has_zero_tax() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, _tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, None),
        )
        assert invoice.tax_total == Decimal("0")
        assert invoice.total == Decimal("200.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_invoice_rejects_due_before_issue() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, _tax_code = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_invoice(
                owner.id,
                client.tenant_id,
                contact_id=contact.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 1),
                lines=_lines(revenue.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_invoice_rejects_empty_lines() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, _revenue, _tax_account, contact, _tax_code = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_invoice(
                owner.id,
                client.tenant_id,
                contact_id=contact.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=[],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_invoice_requires_customer_or_both_role() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, _contact, _tax_code = _setup(owner.id, client.tenant_id)
        supplier_only = create_contact(
            owner.id, client.tenant_id, first_name="Sup", last_name="Plier"
        )
        tag_contact_role(owner.id, client.tenant_id, supplier_only.id, role="supplier")
        with pytest.raises(AccountingValidationError):
            create_invoice(
                owner.id,
                client.tenant_id,
                contact_id=supplier_only.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(revenue.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_invoice_rejects_untagged_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, _contact, _tax_code = _setup(owner.id, client.tenant_id)
        untagged = create_contact(owner.id, client.tenant_id, first_name="No", last_name="Role")
        with pytest.raises(AccountingValidationError):
            create_invoice(
                owner.id,
                client.tenant_id,
                contact_id=untagged.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(revenue.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Update / void (draft-only) ----------------------------------------------


def test_update_and_void_draft_invoice() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        updated = update_invoice(
            owner.id,
            client.tenant_id,
            invoice.id,
            description="Updated memo",
            lines=_lines(revenue.id, None),
        )
        assert updated.description == "Updated memo"
        assert updated.tax_total == Decimal("0")

        voided = void_invoice(owner.id, client.tenant_id, invoice.id)
        assert voided.status == "voided"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Posting: numbering, journal balance, period resolution ------------------


def test_post_invoice_assigns_number_and_creates_balanced_journal_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        posted = post_invoice(owner.id, client.tenant_id, invoice.id)
        assert posted.status == "posted"
        assert posted.invoice_number == 1
        assert posted.period_id is not None
        assert posted.journal_entry_id is not None
        assert posted.outstanding_amount == Decimal("242.00")

        from product.accounting.journal import get_journal_entry

        entry = get_journal_entry(owner.id, client.tenant_id, posted.journal_entry_id)
        assert entry.status == "posted"
        total_debits = sum((line.debit_amount for line in entry.lines), Decimal("0"))
        total_credits = sum((line.credit_amount for line in entry.lines), Decimal("0"))
        assert total_debits == total_credits == Decimal("242.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_invoice_numbers_are_gapless_and_sequential() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        numbers = []
        for _ in range(3):
            invoice = create_invoice(
                owner.id,
                client.tenant_id,
                contact_id=contact.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(revenue.id, tax_code.id),
            )
            posted = post_invoice(owner.id, client.tenant_id, invoice.id)
            numbers.append(posted.invoice_number)
        assert numbers == [1, 2, 3]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_already_posted_invoice_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        post_invoice(owner.id, client.tenant_id, invoice.id)
        with pytest.raises(AccountingValidationError):
            post_invoice(owner.id, client.tenant_id, invoice.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_with_no_covering_period_rejected_number_not_consumed() -> None:
    """The numbering advisory lock is acquired *inside* the same
    transaction as period resolution -- a rollback (no covering period)
    must never leave a consumed number, mirroring
    `test_journal_integration.py::test_post_unbalanced_entry_rejected_atomically`'s
    own atomicity proof."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable = create_account(
            owner.id, client.tenant_id, code="1100", name="AR", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Jane", last_name="Customer"
        )
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        # No period created at all this time.
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 6, 1),
            due_date=date(2026, 6, 15),
            lines=_lines(revenue.id),
        )
        with pytest.raises(AccountingPeriodNotFoundError):
            post_invoice(owner.id, client.tenant_id, invoice.id)

        unchanged = get_invoice(owner.id, client.tenant_id, invoice.id)
        assert unchanged.status == "draft"
        assert unchanged.invoice_number is None

        # A second invoice must still get number 1 -- nothing was consumed.
        second = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 6, 1),
            due_date=date(2026, 6, 15),
            lines=_lines(revenue.id),
        )
        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30)
        )
        posted_second = post_invoice(owner.id, client.tenant_id, second.id)
        assert posted_second.invoice_number == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Cancellation -------------------------------------------------------------


def test_cancel_posted_invoice_reverses_journal_and_zeroes_outstanding() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        posted = post_invoice(owner.id, client.tenant_id, invoice.id)
        cancelled = cancel_invoice(owner.id, client.tenant_id, posted.id)
        assert cancelled.status == "cancelled"
        assert cancelled.outstanding_amount == Decimal("0")

        from product.accounting.journal import get_journal_entry

        assert posted.journal_entry_id is not None
        original_entry = get_journal_entry(owner.id, client.tenant_id, posted.journal_entry_id)
        assert original_entry.status == "reversed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancel_is_owner_only() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        posted = post_invoice(member.id, client.tenant_id, invoice.id)
        with pytest.raises(AccountingAccessDeniedError):
            cancel_invoice(member.id, client.tenant_id, posted.id)
        # The owner still can.
        cancelled = cancel_invoice(owner.id, client.tenant_id, posted.id)
        assert cancelled.status == "cancelled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Idempotency --------------------------------------------------------------


def test_repeated_post_with_same_idempotency_key_does_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        key = f"post-{uuid.uuid4()}"
        first = post_invoice(owner.id, client.tenant_id, invoice.id, idempotency_key=key)
        second = post_invoice(owner.id, client.tenant_id, invoice.id, idempotency_key=key)
        assert first.invoice_number == second.invoice_number
        assert first.journal_entry_id == second.journal_entry_id

        entries = list_audit_log(
            client.tenant_id, resource_type="accounting.invoice", resource_id=str(invoice.id)
        )
        posted_entries = [e for e in entries if e.action == "accounting.invoice.posted"]
        assert len(posted_entries) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Events --------------------------------------------------------------


def test_create_and_post_publish_expected_events() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received_types: list[str] = []

    def _handler(event) -> None:
        received_types.append(event.type)

    subscribe(ACCOUNTING_INVOICE_CREATED_EVENT_TYPE, _handler)
    subscribe(ACCOUNTING_INVOICE_POSTED_EVENT_TYPE, _handler)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        post_invoice(owner.id, client.tenant_id, invoice.id)
        assert received_types == [
            ACCOUNTING_INVOICE_CREATED_EVENT_TYPE,
            ACCOUNTING_INVOICE_POSTED_EVENT_TYPE,
        ]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Overdue filter (the Command Center consumer's own real condition) ------


def test_list_invoices_overdue_only_excludes_paid_and_future() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        overdue = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            lines=_lines(revenue.id, tax_code.id),
        )
        post_invoice(owner.id, client.tenant_id, overdue.id)

        not_due_yet = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2099, 1, 1),
            lines=_lines(revenue.id, tax_code.id),
        )
        post_invoice(owner.id, client.tenant_id, not_due_yet.id)

        results = list_invoices(owner.id, client.tenant_id, overdue_only=True)
        result_ids = {r.id for r in results}
        assert overdue.id in result_ids
        assert not_due_yet.id not in result_ids
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation / authorization -----------------------------------------


def test_invoices_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client_a.tenant_id)
        invoice = create_invoice(
            owner.id,
            client_a.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_invoice(owner.id, client_b.tenant_id, invoice.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_or_post() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            create_invoice(
                outsider.id,
                client.tenant_id,
                contact_id=contact.id,
                receivable_account_id=receivable.id,
                currency="EUR",
                issue_date=date(2026, 1, 10),
                due_date=date(2026, 1, 24),
                lines=_lines(revenue.id, tax_code.id),
            )
        invoice = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        with pytest.raises(AccountingAccessDeniedError):
            post_invoice(outsider.id, client.tenant_id, invoice.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


# --- Concurrency: gapless numbering under a real race -------------------------


def test_concurrent_post_never_assigns_duplicate_numbers() -> None:
    """Real concurrency, real Postgres: two drafts posted at the same
    instant by two threads, both racing for
    `f"accounting.invoice_number.{tenant_id}"`. The database's own partial
    unique index (`uq_accounting_invoices_tenant_number`) is the final
    backstop; the advisory lock should make a collision structurally
    unreachable before that. Mirrors
    `test_periods_integration.py::test_concurrent_close_and_post_never_corrupts_state`'s
    own `threading.Barrier`-based shape."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice_a = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )
        invoice_b = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 1, 24),
            lines=_lines(revenue.id, tax_code.id),
        )

        results: dict[str, InvoiceView] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _post(key: str, invoice_id: uuid.UUID) -> None:
            try:
                barrier.wait(timeout=5)
                results[key] = post_invoice(owner.id, client.tenant_id, invoice_id)
            except Exception as exc:  # noqa: BLE001 -- collected, asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=_post, args=("a", invoice_a.id)),
            threading.Thread(target=_post, args=("b", invoice_b.id)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        numbers = {results["a"].invoice_number, results["b"].invoice_number}
        assert numbers == {1, 2}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
