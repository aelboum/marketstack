"""Customer invoices (ADR-0014 Decision 12, docs/ROADMAP.md Phase 25).

**Atomic composition with Phase 24's own ledger, without duplicating its
logic**: `post_invoice()` must allocate the gapless invoice number,
create the invoice's own journal entry, post that entry (balance check +
period resolution/lock), and flip the invoice to `posted` all inside one
transaction -- if any step fails, none of it must be visible (an
allocated number that rolls back on failure is the entire point of
Decision 12's own numbering mechanism; a posted-but-unlinked journal
entry would be a real integrity gap). `product/accounting/journal.py`'s
own public `create_journal_entry()`/`post_journal_entry()`/
`reverse_journal_entry()` each open their *own* `tenant_session_scope()`
-- calling them here would nest a second, separate transaction, breaking
exactly that atomicity. This module instead imports journal.py's own
internal, session-taking `_post_journal_entry_in_session()`/
`_reverse_journal_entry_in_session()` helpers (already factored out
inside journal.py for its own idempotent/plain-path branching) and runs
them inside this module's own transaction -- the real posting/reversal
*logic* (balance enforcement, period resolution, advisory locking, status
transition) is fully reused, never duplicated; only the trivial
`JournalEntry`/`JournalLine` row construction is inlined, because Phase
24 never anticipated a same-transaction caller for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import run_idempotent
from infra.db import acquire_tenant_advisory_lock, delete, select, tenant_session_scope

from product.accounting.contacts import _assert_role
from product.accounting.errors import AccountingReferenceNotFoundError, AccountingValidationError
from product.accounting.journal import (
    _post_journal_entry_in_session,
    _reverse_journal_entry_in_session,
)
from product.accounting.models import (
    CONTACT_ROLE_CUSTOMER,
    DOCUMENT_STATUS_CANCELLED,
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_POSTED,
    DOCUMENT_STATUS_VOIDED,
    JOURNAL_ENTRY_STATUS_DRAFT,
    MAX_DOCUMENT_DESCRIPTION_LENGTH,
    MAX_LINE_DESCRIPTION_LENGTH,
    ZERO,
    Account,
    Invoice,
    InvoiceLine,
    JournalEntry,
    JournalLine,
    TaxCode,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import INVOICE_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_INVOICE_CREATED_EVENT_TYPE = "accounting.invoice.created"
ACCOUNTING_INVOICE_CREATED_EVENT_VERSION = 1
ACCOUNTING_INVOICE_POSTED_EVENT_TYPE = "accounting.invoice.posted"
ACCOUNTING_INVOICE_POSTED_EVENT_VERSION = 1

_CENTS = Decimal("0.01")


def _round(amount: Decimal) -> Decimal:
    """`ROUND_HALF_UP` to 2dp -- the identical convention `product
    .foundation.values.Money.from_decimal()` already established (ADR-0014
    Decision 7 addendum), extended here, not reinvented."""
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _validate_currency(currency: str) -> str:
    """Reuses `Money`'s own currency-shape validation, mirroring
    `product/accounting/journal.py::_validate_currency()` exactly (each
    module keeps its own tiny copy rather than cross-importing a private
    helper across files, matching this codebase's established
    "duplicate a tiny, genuinely shared utility" judgment elsewhere)."""
    normalized = currency.upper()
    Money(minor_units=0, currency=normalized)
    return normalized


def _validate_description(description: str) -> str:
    if len(description) > MAX_DOCUMENT_DESCRIPTION_LENGTH:
        raise AccountingValidationError(
            f"description must be at most {MAX_DOCUMENT_DESCRIPTION_LENGTH} characters."
        )
    return description


@dataclass(frozen=True, slots=True)
class InvoiceLineInput:
    account_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_code_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class InvoiceLineView:
    id: uuid.UUID
    account_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_code_id: uuid.UUID | None
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    invoice_number: int | None
    contact_id: uuid.UUID
    receivable_account_id: uuid.UUID
    currency: str
    status: str
    issue_date: date
    due_date: date
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    outstanding_amount: Decimal
    period_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    description: str | None
    created_by_user_id: uuid.UUID
    posted_by_user_id: uuid.UUID | None
    posted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[InvoiceLineView, ...]


def _line_to_view(line: InvoiceLine) -> InvoiceLineView:
    return InvoiceLineView(
        id=line.id,
        account_id=line.account_id,
        description=line.description,
        quantity=line.quantity,
        unit_price=line.unit_price,
        tax_code_id=line.tax_code_id,
        line_subtotal=line.line_subtotal,
        line_tax=line.line_tax,
        line_total=line.line_total,
    )


def _to_view(row: Invoice, lines: list[InvoiceLine]) -> InvoiceView:
    return InvoiceView(
        id=row.id,
        tenant_id=row.tenant_id,
        invoice_number=row.invoice_number,
        contact_id=row.contact_id,
        receivable_account_id=row.receivable_account_id,
        currency=row.currency,
        status=row.status,
        issue_date=row.issue_date.date(),
        due_date=row.due_date.date(),
        subtotal=row.subtotal,
        tax_total=row.tax_total,
        total=row.total,
        outstanding_amount=row.outstanding_amount,
        period_id=row.period_id,
        journal_entry_id=row.journal_entry_id,
        description=row.description,
        created_by_user_id=row.created_by_user_id,
        posted_by_user_id=row.posted_by_user_id,
        posted_at=row.posted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        lines=tuple(_line_to_view(line) for line in lines),
    )


def _compute_line_totals(
    session,
    tenant_id: uuid.UUID,
    line: InvoiceLineInput,
    *,
    tax_code_cache: dict[uuid.UUID, TaxCode],
) -> tuple[Decimal, Decimal, Decimal]:
    """ADR-0014 Decision 7 addendum: `line_subtotal = ROUND(quantity *
    unit_price, 2)`, `line_tax = ROUND(line_subtotal * rate / 100, 2)` --
    never re-rounded or back-distributed at the document level. A `NULL`
    `tax_code_id` is an untaxed line (`line_tax = 0`), not an error."""
    if line.quantity <= 0:
        raise AccountingValidationError("quantity must be positive.")
    if line.unit_price < 0:
        raise AccountingValidationError("unit_price must not be negative.")
    line_subtotal = _round(line.quantity * line.unit_price)
    line_tax = ZERO
    if line.tax_code_id is not None:
        tax_code = tax_code_cache.get(line.tax_code_id)
        if tax_code is None:
            tax_code = session.get(TaxCode, line.tax_code_id)
            if tax_code is None or tax_code.tenant_id != tenant_id:
                raise AccountingReferenceNotFoundError("tax_code", line.tax_code_id)
            tax_code_cache[line.tax_code_id] = tax_code
        line_tax = _round(line_subtotal * tax_code.rate_percent / Decimal(100))
    return line_subtotal, line_tax, line_subtotal + line_tax


def _validate_lines(
    session, tenant_id: uuid.UUID, lines: list[InvoiceLineInput]
) -> list[tuple[InvoiceLineInput, Decimal, Decimal, Decimal]]:
    if not lines:
        raise AccountingValidationError("an invoice needs at least one line.")
    tax_code_cache: dict[uuid.UUID, TaxCode] = {}
    validated: list[tuple[InvoiceLineInput, Decimal, Decimal, Decimal]] = []
    for line in lines:
        if not line.description or not line.description.strip():
            raise AccountingValidationError("each line needs a non-empty description.")
        if len(line.description) > MAX_LINE_DESCRIPTION_LENGTH:
            raise AccountingValidationError(
                f"line description must be at most {MAX_LINE_DESCRIPTION_LENGTH} characters."
            )
        account = session.get(Account, line.account_id)
        if account is None or account.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", line.account_id)
        if not account.is_active:
            raise AccountingValidationError(f"account {line.account_id} is not active.")
        line_subtotal, line_tax, line_total = _compute_line_totals(
            session, tenant_id, line, tax_code_cache=tax_code_cache
        )
        validated.append((line, line_subtotal, line_tax, line_total))
    return validated


def create_invoice(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    receivable_account_id: uuid.UUID,
    currency: str,
    issue_date: date,
    due_date: date,
    lines: list[InvoiceLineInput],
    description: str | None = None,
    idempotency_key: str | None = None,
) -> InvoiceView:
    """`subtotal`/`tax_total`/`total` are always derived from `lines`,
    never caller-supplied (Decision 12). `invoice_number` stays `NULL`
    until `post_invoice()` -- a draft has no financial effect and may be
    edited freely (mirrors `JournalEntry`'s own Decision 3 discipline)."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="create")
    if due_date < issue_date:
        raise AccountingValidationError("due_date must not be before issue_date.")
    validated_currency = _validate_currency(currency)
    validated_description = _validate_description(description) if description else None

    def _business(session) -> dict[str, object]:
        _assert_role(session, tenant_id, contact_id, required_role=CONTACT_ROLE_CUSTOMER)
        validated_lines = _validate_lines(session, tenant_id, lines)
        receivable = session.get(Account, receivable_account_id)
        if receivable is None or receivable.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", receivable_account_id)

        subtotal = sum((v[1] for v in validated_lines), ZERO)
        tax_total = sum((v[2] for v in validated_lines), ZERO)

        invoice_id = uuid.uuid4()
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=tenant_id,
                contact_id=contact_id,
                receivable_account_id=receivable_account_id,
                currency=validated_currency,
                status=DOCUMENT_STATUS_DRAFT,
                issue_date=_date_to_utc_midnight(issue_date),
                due_date=_date_to_utc_midnight(due_date),
                subtotal=subtotal,
                tax_total=tax_total,
                total=subtotal + tax_total,
                outstanding_amount=ZERO,
                description=validated_description,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()
        for line_no, (line, line_subtotal, line_tax, line_total) in enumerate(
            validated_lines, start=1
        ):
            session.add(
                InvoiceLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    line_no=line_no,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    account_id=line.account_id,
                    tax_code_id=line.tax_code_id,
                    line_subtotal=line_subtotal,
                    line_tax=line_tax,
                    line_total=line_total,
                )
            )
        session.flush()
        return {"invoice_id": str(invoice_id)}

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _business(session)
        is_replay = False
    else:
        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.invoice.create",
            idempotency_key,
            fingerprint_payload={
                "contact_id": str(contact_id),
                "currency": validated_currency,
                "line_count": len(lines),
            },
            business_fn=_business,
        )

    invoice_id = uuid.UUID(str(result["invoice_id"]))
    view = _load_view(tenant_id, invoice_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.invoice.created",
            resource_type="accounting.invoice",
            resource_id=str(invoice_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"contact_id": str(contact_id), "line_count": len(view.lines)},
        )
        publish(
            Event(
                type=ACCOUNTING_INVOICE_CREATED_EVENT_TYPE,
                version=ACCOUNTING_INVOICE_CREATED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"invoice_id": str(invoice_id), "contact_id": str(contact_id)},
            )
        )
    return view


def _load_view(tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> InvoiceView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Invoice, invoice_id)
        assert row is not None
        lines = (
            session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.tenant_id == tenant_id, InvoiceLine.invoice_id == invoice_id)
                .order_by(InvoiceLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
        session.expunge(row)
        for line in lines:
            session.expunge(line)
    return view


def _get_owned_row(session, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    row = session.get(Invoice, invoice_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("invoice", invoice_id)
    return row


def get_invoice(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, invoice_id: uuid.UUID
) -> InvoiceView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, invoice_id)
        lines = (
            session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.tenant_id == tenant_id, InvoiceLine.invoice_id == invoice_id)
                .order_by(InvoiceLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
    return view


def list_invoices(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    overdue_only: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[InvoiceView]:
    """`overdue_only=True` -- `status == 'posted'` and `outstanding_amount
    > 0` and `due_date` in the past -- the exact real condition the Phase
    25 Command Center consumer uses (`product/accounting/routes.py`), not
    a separate query duplicated there."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        query = select(Invoice).where(Invoice.tenant_id == tenant_id)
        if status is not None:
            query = query.where(Invoice.status == status)
        if overdue_only:
            query = query.where(
                Invoice.status == DOCUMENT_STATUS_POSTED,
                Invoice.outstanding_amount > ZERO,
                Invoice.due_date < datetime.now(UTC),
            )
        rows = (
            session.execute(
                query.order_by(Invoice.due_date.asc()).limit(bounded_limit).offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        views = []
        for row in rows:
            lines = (
                session.execute(
                    select(InvoiceLine)
                    .where(InvoiceLine.tenant_id == tenant_id, InvoiceLine.invoice_id == row.id)
                    .order_by(InvoiceLine.line_no.asc())
                )
                .scalars()
                .all()
            )
            views.append(_to_view(row, list(lines)))
    return views


def update_invoice(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    description: str | None = ...,  # type: ignore[assignment] -- sentinel: omitted vs. explicit None
    lines: list[InvoiceLineInput] | None = None,
    due_date: date | None = None,
) -> InvoiceView:
    """Only while `status == draft`."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, invoice_id)
        if row.status != DOCUMENT_STATUS_DRAFT:
            raise AccountingValidationError(
                f"invoice {invoice_id} cannot be edited while status={row.status!r} "
                "(only 'draft' invoices can be)."
            )
        if description is not ...:
            row.description = _validate_description(description) if description else None
        if due_date is not None:
            if due_date < row.issue_date.date():
                raise AccountingValidationError("due_date must not be before issue_date.")
            row.due_date = _date_to_utc_midnight(due_date)
        if lines is not None:
            validated_lines = _validate_lines(session, tenant_id, lines)
            session.execute(
                delete(InvoiceLine).where(
                    InvoiceLine.tenant_id == tenant_id, InvoiceLine.invoice_id == invoice_id
                )
            )
            session.flush()
            for line_no, (line, line_subtotal, line_tax, line_total) in enumerate(
                validated_lines, start=1
            ):
                session.add(
                    InvoiceLine(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        invoice_id=invoice_id,
                        line_no=line_no,
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        account_id=line.account_id,
                        tax_code_id=line.tax_code_id,
                        line_subtotal=line_subtotal,
                        line_tax=line_tax,
                        line_total=line_total,
                    )
                )
            row.subtotal = sum((v[1] for v in validated_lines), ZERO)
            row.tax_total = sum((v[2] for v in validated_lines), ZERO)
            row.total = row.subtotal + row.tax_total
        session.flush()

    view = _load_view(tenant_id, invoice_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.invoice.updated",
        resource_type="accounting.invoice",
        resource_id=str(invoice_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"line_count": len(view.lines)},
    )
    return view


def void_invoice(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, invoice_id: uuid.UUID
) -> InvoiceView:
    """`draft -> voided` -- discarding something never posted, never
    consumed a number. Mirrors `journal.py::void_journal_entry()`."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="void")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Invoice, invoice_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("invoice", invoice_id)
        if row.status != DOCUMENT_STATUS_DRAFT:
            raise AccountingValidationError(
                f"invoice {invoice_id} cannot be voided while status={row.status!r} "
                "(only 'draft' invoices can be)."
            )
        row.status = DOCUMENT_STATUS_VOIDED
        session.flush()

    view = _load_view(tenant_id, invoice_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.invoice.voided",
        resource_type="accounting.invoice",
        resource_id=str(invoice_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


def _post_invoice_in_session(
    session, tenant_id: uuid.UUID, invoice_id: uuid.UUID, actor_user_id: uuid.UUID
) -> dict[str, object]:
    row = session.get(Invoice, invoice_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("invoice", invoice_id)
    if row.status != DOCUMENT_STATUS_DRAFT:
        raise AccountingValidationError(
            f"invoice {invoice_id} cannot be posted while status={row.status!r} "
            "(only 'draft' invoices can be)."
        )

    lines = (
        session.execute(
            select(InvoiceLine).where(
                InvoiceLine.tenant_id == tenant_id, InvoiceLine.invoice_id == invoice_id
            )
        )
        .scalars()
        .all()
    )
    if not lines:
        raise AccountingValidationError(f"invoice {invoice_id} needs at least one line to post.")

    subtotal = sum((line.line_subtotal for line in lines), ZERO)
    tax_total = sum((line.line_tax for line in lines), ZERO)
    total = subtotal + tax_total
    if total <= ZERO:
        raise AccountingValidationError(f"invoice {invoice_id} total must be positive to post.")

    # Gapless per-tenant numbering (ADR-0014 Decision 12): tenant-wide
    # advisory lock, number allocated only here, inside this same
    # transaction -- a rollback below (unbalanced entry, closed period)
    # never leaves a consumed number, by construction.
    acquire_tenant_advisory_lock(session, tenant_id, f"accounting.invoice_number.{tenant_id}")
    last_number = session.execute(
        select(Invoice.invoice_number)
        .where(Invoice.tenant_id == tenant_id, Invoice.invoice_number.is_not(None))
        .order_by(Invoice.invoice_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    next_number = (last_number or 0) + 1

    # Build the journal entry: Dr receivable for the full total; Cr each
    # line's own account for its line_subtotal; Cr each distinct tax
    # account for its aggregated line_tax (Decision 7 addendum).
    journal_entry_id = uuid.uuid4()
    session.add(
        JournalEntry(
            id=journal_entry_id,
            tenant_id=tenant_id,
            entry_date=row.issue_date,
            currency=row.currency,
            description=f"Invoice {next_number}",
            status=JOURNAL_ENTRY_STATUS_DRAFT,
            created_by_user_id=actor_user_id,
        )
    )
    session.flush()
    session.add(
        JournalLine(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            journal_entry_id=journal_entry_id,
            account_id=row.receivable_account_id,
            debit_amount=total,
            credit_amount=ZERO,
        )
    )
    tax_by_account: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=line.account_id,
                debit_amount=ZERO,
                credit_amount=line.line_subtotal,
            )
        )
        if line.line_tax > ZERO and line.tax_code_id is not None:
            tax_code = session.get(TaxCode, line.tax_code_id)
            assert tax_code is not None  # validated at create/update time
            tax_by_account[tax_code.tax_account_id] = (
                tax_by_account.get(tax_code.tax_account_id, ZERO) + line.line_tax
            )
    for tax_account_id, amount in tax_by_account.items():
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=tax_account_id,
                debit_amount=ZERO,
                credit_amount=amount,
            )
        )
    session.flush()

    # Reuses Phase 24's own posting logic completely -- balance
    # enforcement, period resolution, advisory locking, status transition
    # (module docstring: never duplicated).
    post_result = _post_journal_entry_in_session(
        session, tenant_id, journal_entry_id, actor_user_id
    )

    row.invoice_number = next_number
    row.subtotal = subtotal
    row.tax_total = tax_total
    row.total = total
    row.outstanding_amount = total
    row.period_id = uuid.UUID(str(post_result["period_id"]))
    row.journal_entry_id = journal_entry_id
    row.status = DOCUMENT_STATUS_POSTED
    row.posted_by_user_id = actor_user_id
    row.posted_at = datetime.now(UTC)
    session.flush()
    return {
        "invoice_id": str(invoice_id),
        "invoice_number": next_number,
        "journal_entry_id": str(journal_entry_id),
        "period_id": str(post_result["period_id"]),
    }


def post_invoice(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> InvoiceView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="post")

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _post_invoice_in_session(session, tenant_id, invoice_id, actor_user_id)
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _post_invoice_in_session(session, tenant_id, invoice_id, actor_user_id)

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.invoice.post",
            idempotency_key,
            fingerprint_payload={"invoice_id": str(invoice_id)},
            business_fn=_business,
        )

    view = _load_view(tenant_id, invoice_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.invoice.posted",
            resource_type="accounting.invoice",
            resource_id=str(invoice_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={
                "invoice_number": str(result["invoice_number"]),
                "journal_entry_id": str(result["journal_entry_id"]),
            },
        )
        publish(
            Event(
                type=ACCOUNTING_INVOICE_POSTED_EVENT_TYPE,
                version=ACCOUNTING_INVOICE_POSTED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={
                    "invoice_id": str(invoice_id),
                    "contact_id": str(view.contact_id),
                    "journal_entry_id": str(result["journal_entry_id"]),
                },
            )
        )
    return view


def cancel_invoice(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    cancellation_date: date | None = None,
) -> InvoiceView:
    """`posted -> cancelled` -- reverses the invoice's own linked journal
    entry (reusing `journal.py`'s internal reversal logic, same atomicity
    reasoning as `post_invoice()`), then zeroes `outstanding_amount`
    (a cancelled invoice is no longer owed). Owner-only (ADR-0014 Decision
    13) -- enforced by `require()` below, not re-stated here."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="cancel")
    resolved_date = cancellation_date if cancellation_date is not None else datetime.now(UTC).date()

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Invoice, invoice_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("invoice", invoice_id)
        if row.status != DOCUMENT_STATUS_POSTED:
            raise AccountingValidationError(
                f"invoice {invoice_id} cannot be cancelled while status={row.status!r} "
                "(only 'posted' invoices can be)."
            )
        assert row.journal_entry_id is not None  # true for every posted invoice
        _reverse_journal_entry_in_session(
            session,
            tenant_id,
            row.journal_entry_id,
            actor_user_id,
            resolved_date,
            f"Cancellation of invoice {row.invoice_number}",
        )
        row.status = DOCUMENT_STATUS_CANCELLED
        row.outstanding_amount = ZERO
        session.flush()

    view = _load_view(tenant_id, invoice_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.invoice.cancelled",
        resource_type="accounting.invoice",
        resource_id=str(invoice_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


__all__ = [
    "ACCOUNTING_INVOICE_CREATED_EVENT_TYPE",
    "ACCOUNTING_INVOICE_POSTED_EVENT_TYPE",
    "InvoiceLineInput",
    "InvoiceLineView",
    "InvoiceView",
    "cancel_invoice",
    "create_invoice",
    "get_invoice",
    "list_invoices",
    "post_invoice",
    "update_invoice",
    "void_invoice",
]
