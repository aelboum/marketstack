"""`product/accounting/credit_notes.py`: credit-note lifecycle, tax
calculation, gapless numbering (a sequence independent from
`Invoice.invoice_number`), atomic journal posting, invoice immutability,
authorization, tenant isolation, and events (docs/ROADMAP.md Phase 15.3).
Real disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from infra.db import select, tenant_session_scope
from product.accounting.accounts import create_account
from product.accounting.contacts import tag_contact_role
from product.accounting.credit_notes import (
    ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE,
    ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE,
    CreditNoteLineInput,
    CreditNoteView,
    create_credit_note,
    get_credit_note,
    list_credit_notes_for_invoice,
    post_credit_note,
    void_credit_note,
)
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.invoices import InvoiceLineInput, create_invoice, get_invoice, post_invoice
from product.accounting.models import JournalLine
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
    """Identical fixture shape to `test_invoices_integration.py::_setup()`
    -- receivable + revenue + tax accounts, a covering open period, a
    tagged customer contact, one 21% sales tax code."""
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


def _invoice_lines(revenue_id, tax_code_id=None):
    return [
        InvoiceLineInput(
            account_id=revenue_id,
            description="Consulting",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            tax_code_id=tax_code_id,
        )
    ]


def _credit_note_lines(revenue_id, tax_code_id=None, *, quantity="1"):
    return [
        CreditNoteLineInput(
            account_id=revenue_id,
            description="Returned unit",
            quantity=Decimal(quantity),
            unit_price=Decimal("100.00"),
            tax_code_id=tax_code_id,
        )
    ]


def _posted_invoice(owner_id, tenant_id, receivable_id, revenue_id, contact_id, tax_code_id):
    invoice = create_invoice(
        owner_id,
        tenant_id,
        contact_id=contact_id,
        receivable_account_id=receivable_id,
        currency="EUR",
        issue_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=_invoice_lines(revenue_id, tax_code_id),
    )
    return post_invoice(owner_id, tenant_id, invoice.id)


# --- Creation / tax calculation ----------------------------------------------


def test_create_credit_note_computes_tax_and_totals() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        credit_note = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="eur",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        assert credit_note.status == "draft"
        assert credit_note.credit_note_number is None
        assert credit_note.currency == "EUR"
        assert credit_note.invoice_id == invoice.id
        assert credit_note.subtotal == Decimal("100.00")
        assert credit_note.tax_total == Decimal("21.00")
        assert credit_note.total == Decimal("121.00")
        assert len(credit_note.lines) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_credit_note_rejects_draft_invoice() -> None:
    """`docs/ACCOUNTING-SCOPE.md`'s own "Credit notes" entry: a credit note
    corrects an already-*issued* invoice -- a draft has nothing to
    correct."""
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
            lines=_invoice_lines(revenue.id, tax_code.id),
        )
        with pytest.raises(AccountingValidationError):
            create_credit_note(
                owner.id,
                client.tenant_id,
                invoice_id=invoice.id,
                currency="EUR",
                issue_date=date(2026, 1, 15),
                lines=_credit_note_lines(revenue.id, tax_code.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_credit_note_rejects_empty_lines() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        with pytest.raises(AccountingValidationError):
            create_credit_note(
                owner.id,
                client.tenant_id,
                invoice_id=invoice.id,
                currency="EUR",
                issue_date=date(2026, 1, 15),
                lines=[],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Posting / invoice immutability -------------------------------------------


def test_post_credit_note_assigns_number_and_posts_balanced_journal_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        posted = post_credit_note(owner.id, client.tenant_id, draft.id)

        assert posted.status == "posted"
        assert posted.credit_note_number == 1
        assert posted.journal_entry_id is not None
        assert posted.period_id is not None

        with tenant_session_scope(client.tenant_id) as session:
            rows = (
                session.execute(
                    select(JournalLine).where(
                        JournalLine.tenant_id == client.tenant_id,
                        JournalLine.journal_entry_id == posted.journal_entry_id,
                    )
                )
                .scalars()
                .all()
            )
            # Materialize the plain values needed below before the session
            # (and thus these ORM instances) closes -- accessing an
            # attribute on a detached instance after the `with` block would
            # raise `DetachedInstanceError`.
            lines = [(row.account_id, row.debit_amount, row.credit_amount) for row in rows]
        total_debits = sum((debit for _account_id, debit, _credit in lines), Decimal("0"))
        total_credits = sum((credit for _account_id, _debit, credit in lines), Decimal("0"))
        assert total_debits == total_credits == Decimal("121.00")
        # Dr revenue (100.00) + Dr VAT payable (21.00), Cr receivable (121.00).
        receivable_line = next(line for line in lines if line[0] == receivable.id)
        assert receivable_line[2] == Decimal("121.00")  # credit
        assert receivable_line[1] == Decimal("0")  # debit
        revenue_line = next(line for line in lines if line[0] == revenue.id)
        assert revenue_line[1] == Decimal("100.00")  # debit
        tax_line = next(line for line in lines if line[0] == tax_account.id)
        assert tax_line[1] == Decimal("21.00")  # debit
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_credit_note_never_mutates_the_original_invoice() -> None:
    """The core Phase 15.3 requirement, verified directly: every one of the
    invoice's own fields is byte-identical before and after the credit
    note referencing it is created and posted."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice_before = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice_before.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        post_credit_note(owner.id, client.tenant_id, draft.id)

        invoice_after = get_invoice(owner.id, client.tenant_id, invoice_before.id)
        assert invoice_after == invoice_before
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_credit_note_reference_is_always_resolvable() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        posted = post_credit_note(owner.id, client.tenant_id, draft.id)

        fetched = get_credit_note(owner.id, client.tenant_id, posted.id)
        assert fetched.invoice_id == invoice.id

        listed = list_credit_notes_for_invoice(owner.id, client.tenant_id, invoice.id)
        assert [cn.id for cn in listed] == [posted.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_void_credit_note_discards_a_draft_without_consuming_a_number() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        voided = void_credit_note(owner.id, client.tenant_id, draft.id)
        assert voided.status == "voided"

        # A subsequently posted credit note still gets number 1 -- the
        # voided draft never consumed one.
        second_draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 16),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        posted = post_credit_note(owner.id, client.tenant_id, second_draft.id)
        assert posted.credit_note_number == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Authorization / tenant isolation ------------------------------------------------


def test_unrelated_actor_cannot_create_credit_note() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        with pytest.raises(AccountingAccessDeniedError):
            create_credit_note(
                unrelated.id,
                client.tenant_id,
                invoice_id=invoice.id,
                currency="EUR",
                issue_date=date(2026, 1, 15),
                lines=_credit_note_lines(revenue.id, tax_code.id),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_create_and_post_credit_note() -> None:
    """`CREDIT_NOTE_RESOURCE` has no higher-risk action withheld from
    `member` (`product/accounting/permissions.py`'s own module docstring)
    -- unlike `INVOICE_RESOURCE.cancel`, posting a credit note is not
    owner-only."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        _add_member(owner.id, client.tenant_id, member.id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            member.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        posted = post_credit_note(member.id, client.tenant_id, draft.id)
        assert posted.status == "posted"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_credit_notes_are_isolated_across_tenants() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        receivable_a, revenue_a, _tax_a, contact_a, tax_code_a = _setup(
            owner_a.id, client_a.tenant_id
        )
        invoice_a = _posted_invoice(
            owner_a.id,
            client_a.tenant_id,
            receivable_a.id,
            revenue_a.id,
            contact_a.id,
            tax_code_a.id,
        )
        draft = create_credit_note(
            owner_a.id,
            client_a.tenant_id,
            invoice_id=invoice_a.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue_a.id, tax_code_a.id),
        )
        credit_note = post_credit_note(owner_a.id, client_a.tenant_id, draft.id)

        _setup(owner_b.id, client_b.tenant_id)
        with pytest.raises(AccountingReferenceNotFoundError):
            get_credit_note(owner_b.id, client_b.tenant_id, credit_note.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


# --- Concurrency ---------------------------------------------------------------------


def test_concurrent_post_never_assigns_duplicate_credit_note_numbers() -> None:
    """Real concurrency, real Postgres: two drafts posted at the same
    instant by two threads, both racing for
    `f"accounting.credit_note_number.{tenant_id}"`. Mirrors
    `test_invoices_integration.py::test_concurrent_post_never_assigns_duplicate_numbers()`'s
    own `threading.Barrier`-based shape exactly, against this table's own,
    separate numbering sequence."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft_a = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        draft_b = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )

        results: dict[str, CreditNoteView] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _post(key: str, credit_note_id: uuid.UUID) -> None:
            try:
                barrier.wait(timeout=5)
                results[key] = post_credit_note(owner.id, client.tenant_id, credit_note_id)
            except Exception as exc:  # noqa: BLE001 -- collected, asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=_post, args=("a", draft_a.id)),
            threading.Thread(target=_post, args=("b", draft_b.id)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        numbers = {results["a"].credit_note_number, results["b"].credit_note_number}
        assert numbers == {1, 2}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Events ---------------------------------------------------------------------------


def test_create_and_post_publish_events() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received: list[str] = []
    subscribe(ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE, lambda event: received.append(event.type))
    subscribe(ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE, lambda event: received.append(event.type))
    try:
        receivable, revenue, _tax_account, contact, tax_code = _setup(owner.id, client.tenant_id)
        invoice = _posted_invoice(
            owner.id, client.tenant_id, receivable.id, revenue.id, contact.id, tax_code.id
        )
        draft = create_credit_note(
            owner.id,
            client.tenant_id,
            invoice_id=invoice.id,
            currency="EUR",
            issue_date=date(2026, 1, 15),
            lines=_credit_note_lines(revenue.id, tax_code.id),
        )
        post_credit_note(owner.id, client.tenant_id, draft.id)
        assert received == [
            ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE,
            ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE,
        ]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
