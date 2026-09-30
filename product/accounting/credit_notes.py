"""Credit notes (docs/ROADMAP.md Phase 15.3 -- deferred by Phase 25's own
explicit scope note: "Credit notes (original 15.3)... remain separately
sequenced, deferred... not pulled forward by this phase" -- implemented
here, separately, once Phase 25's invoice/journal foundation existed to
reference).

**Never mutates the `Invoice` it corrects** -- this is Phase 15.3's own,
literal, minimal Tests requirement ("a credit note never mutates the
original invoice; the reference is always resolvable"), and this module
is deliberately narrower than that requirement's surrounding intuition
might suggest: no function here writes to any `Invoice`/`InvoiceLine`
column, including `Invoice.outstanding_amount` -- see `CreditNote`'s own
class docstring (`product/accounting/models.py`) for why reconciling a
credit note against what a customer still owes is a real, separate,
NOT-yet-specified design decision this phase does not make, rather than a
gap silently left open.

**Atomic composition with Phase 24's own ledger, mirroring
`product/accounting/invoices.py::post_invoice()`'s own reasoning exactly**:
`post_credit_note()` allocates the gapless credit-note number, creates and
posts the credit note's own journal entry, and flips the credit note to
`posted`, all inside one transaction -- via journal.py's own internal,
session-taking `_post_journal_entry_in_session()` helper, never its public
`post_journal_entry()` (which would open a second, nested transaction).

**Journal entry shape -- the mirror image of `post_invoice()`'s own**: an
invoice posts Dr receivable / Cr revenue+tax; a credit note posts Dr
revenue+tax (reversing the recognized revenue) / Cr receivable (reducing
what is owed) -- for the credit note's own line amounts, which may be a
subset of the original invoice's lines (a partial credit is a real,
common case, e.g. one returned item on a multi-line invoice), never
assumed to exactly mirror the full original invoice.

**Gating**: a credit note may only be created against an invoice that is
itself `posted` (an already-issued invoice is what Phase 15.3's own
`docs/ACCOUNTING-SCOPE.md` "Credit notes" entry says a credit note
corrects) -- a `draft` invoice is simply edited or voided directly, never
credited.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import acquire_tenant_advisory_lock, select, tenant_session_scope

from product.accounting.errors import AccountingReferenceNotFoundError, AccountingValidationError
from product.accounting.journal import _post_journal_entry_in_session
from product.accounting.models import (
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_POSTED,
    DOCUMENT_STATUS_VOIDED,
    JOURNAL_ENTRY_STATUS_DRAFT,
    MAX_DOCUMENT_DESCRIPTION_LENGTH,
    MAX_LINE_DESCRIPTION_LENGTH,
    ZERO,
    Account,
    CreditNote,
    CreditNoteLine,
    Invoice,
    JournalEntry,
    JournalLine,
    TaxCode,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import CREDIT_NOTE_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE = "accounting.credit_note.created"
ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_VERSION = 1
ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE = "accounting.credit_note.posted"
ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_VERSION = 1

_CENTS = Decimal("0.01")


def _round(amount: Decimal) -> Decimal:
    """`ROUND_HALF_UP` to 2dp -- the identical convention `product
    .accounting.invoices._round()` already established, duplicated here
    rather than cross-imported (mirrors that module's own "each module
    keeps its own tiny copy" judgment)."""
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _validate_currency(currency: str) -> str:
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
class CreditNoteLineInput:
    account_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_code_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CreditNoteLineView:
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
class CreditNoteView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    credit_note_number: int | None
    invoice_id: uuid.UUID
    currency: str
    status: str
    issue_date: date
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    period_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    description: str | None
    created_by_user_id: uuid.UUID
    posted_by_user_id: uuid.UUID | None
    posted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[CreditNoteLineView, ...]


def _line_to_view(line: CreditNoteLine) -> CreditNoteLineView:
    return CreditNoteLineView(
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


def _to_view(row: CreditNote, lines: list[CreditNoteLine]) -> CreditNoteView:
    return CreditNoteView(
        id=row.id,
        tenant_id=row.tenant_id,
        credit_note_number=row.credit_note_number,
        invoice_id=row.invoice_id,
        currency=row.currency,
        status=row.status,
        issue_date=row.issue_date.date(),
        subtotal=row.subtotal,
        tax_total=row.tax_total,
        total=row.total,
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
    line: CreditNoteLineInput,
    *,
    tax_code_cache: dict[uuid.UUID, TaxCode],
) -> tuple[Decimal, Decimal, Decimal]:
    """Identical arithmetic to `invoices.py::_compute_line_totals()`
    (ADR-0014 Decision 7 addendum): `line_subtotal = ROUND(quantity *
    unit_price, 2)`, `line_tax = ROUND(line_subtotal * rate / 100, 2)`."""
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
    session, tenant_id: uuid.UUID, lines: list[CreditNoteLineInput]
) -> list[tuple[CreditNoteLineInput, Decimal, Decimal, Decimal]]:
    if not lines:
        raise AccountingValidationError("a credit note needs at least one line.")
    tax_code_cache: dict[uuid.UUID, TaxCode] = {}
    validated: list[tuple[CreditNoteLineInput, Decimal, Decimal, Decimal]] = []
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


def _get_owned_invoice(session, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None or invoice.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("invoice", invoice_id)
    return invoice


def create_credit_note(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    invoice_id: uuid.UUID,
    currency: str,
    issue_date: date,
    lines: list[CreditNoteLineInput],
    description: str | None = None,
) -> CreditNoteView:
    """`credit_note_number` stays `NULL` until `post_credit_note()` -- a
    draft has no financial effect and may be discarded via
    `void_credit_note()` freely (mirrors `create_invoice()`'s identical
    discipline). The referenced invoice must already be `posted` (module
    docstring's own "Gating" section) -- read, never locked or mutated."""
    require(actor_user_id, tenant_id, resource=CREDIT_NOTE_RESOURCE, action="create")
    validated_currency = _validate_currency(currency)
    validated_description = _validate_description(description) if description else None

    with tenant_session_scope(tenant_id) as session:
        invoice = _get_owned_invoice(session, tenant_id, invoice_id)
        if invoice.status != DOCUMENT_STATUS_POSTED:
            raise AccountingValidationError(
                f"invoice {invoice_id} cannot be credited while status={invoice.status!r} "
                "(only 'posted' invoices can be)."
            )
        validated_lines = _validate_lines(session, tenant_id, lines)

        subtotal = sum((v[1] for v in validated_lines), ZERO)
        tax_total = sum((v[2] for v in validated_lines), ZERO)

        credit_note_id = uuid.uuid4()
        session.add(
            CreditNote(
                id=credit_note_id,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                currency=validated_currency,
                status=DOCUMENT_STATUS_DRAFT,
                issue_date=_date_to_utc_midnight(issue_date),
                subtotal=subtotal,
                tax_total=tax_total,
                total=subtotal + tax_total,
                description=validated_description,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()
        for line_no, (line, line_subtotal, line_tax, line_total) in enumerate(
            validated_lines, start=1
        ):
            session.add(
                CreditNoteLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    credit_note_id=credit_note_id,
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

    view = _load_view(tenant_id, credit_note_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.credit_note.created",
        resource_type="accounting.credit_note",
        resource_id=str(credit_note_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"invoice_id": str(invoice_id), "line_count": len(view.lines)},
    )
    publish(
        Event(
            type=ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE,
            version=ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"credit_note_id": str(credit_note_id), "invoice_id": str(invoice_id)},
        )
    )
    return view


def _load_view(tenant_id: uuid.UUID, credit_note_id: uuid.UUID) -> CreditNoteView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CreditNote, credit_note_id)
        assert row is not None
        lines = (
            session.execute(
                select(CreditNoteLine)
                .where(
                    CreditNoteLine.tenant_id == tenant_id,
                    CreditNoteLine.credit_note_id == credit_note_id,
                )
                .order_by(CreditNoteLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        return _to_view(row, list(lines))


def _get_owned_row(session, tenant_id: uuid.UUID, credit_note_id: uuid.UUID) -> CreditNote:
    row = session.get(CreditNote, credit_note_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("credit_note", credit_note_id)
    return row


def get_credit_note(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, credit_note_id: uuid.UUID
) -> CreditNoteView:
    require(actor_user_id, tenant_id, resource=CREDIT_NOTE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        _get_owned_row(session, tenant_id, credit_note_id)
    return _load_view(tenant_id, credit_note_id)


def list_credit_notes_for_invoice(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CreditNoteView]:
    """Every credit note referencing `invoice_id` -- the reference is
    always resolvable in the forward direction too (module docstring's own
    Phase 15.3 Tests requirement), never only invoice-to-nothing."""
    require(actor_user_id, tenant_id, resource=CREDIT_NOTE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        _get_owned_invoice(session, tenant_id, invoice_id)
        rows = (
            session.execute(
                select(CreditNote)
                .where(CreditNote.tenant_id == tenant_id, CreditNote.invoice_id == invoice_id)
                .order_by(CreditNote.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        views = []
        for row in rows:
            lines = (
                session.execute(
                    select(CreditNoteLine)
                    .where(
                        CreditNoteLine.tenant_id == tenant_id,
                        CreditNoteLine.credit_note_id == row.id,
                    )
                    .order_by(CreditNoteLine.line_no.asc())
                )
                .scalars()
                .all()
            )
            views.append(_to_view(row, list(lines)))
        return views


def void_credit_note(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, credit_note_id: uuid.UUID
) -> CreditNoteView:
    """`draft -> voided` -- discarding something never posted, never
    consumed a number. Mirrors `invoices.py::void_invoice()`."""
    require(actor_user_id, tenant_id, resource=CREDIT_NOTE_RESOURCE, action="void")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CreditNote, credit_note_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("credit_note", credit_note_id)
        if row.status != DOCUMENT_STATUS_DRAFT:
            raise AccountingValidationError(
                f"credit note {credit_note_id} cannot be voided while status={row.status!r} "
                "(only 'draft' credit notes can be)."
            )
        row.status = DOCUMENT_STATUS_VOIDED
        session.flush()

    view = _load_view(tenant_id, credit_note_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.credit_note.voided",
        resource_type="accounting.credit_note",
        resource_id=str(credit_note_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


def _post_credit_note_in_session(
    session, tenant_id: uuid.UUID, credit_note_id: uuid.UUID, actor_user_id: uuid.UUID
) -> dict[str, object]:
    row = session.get(CreditNote, credit_note_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("credit_note", credit_note_id)
    if row.status != DOCUMENT_STATUS_DRAFT:
        raise AccountingValidationError(
            f"credit note {credit_note_id} cannot be posted while status={row.status!r} "
            "(only 'draft' credit notes can be)."
        )

    # Read-only: the referenced invoice is never locked or written to
    # (module docstring's own "never mutates the Invoice" guarantee) --
    # only its receivable_account_id is needed, to credit the same
    # account the original invoice debited.
    invoice = session.get(Invoice, row.invoice_id)
    if invoice is None or invoice.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("invoice", row.invoice_id)
    if invoice.status != DOCUMENT_STATUS_POSTED:
        raise AccountingValidationError(
            f"invoice {row.invoice_id} is no longer 'posted' (status={invoice.status!r}) -- "
            "this credit note can no longer be posted against it."
        )

    lines = (
        session.execute(
            select(CreditNoteLine).where(
                CreditNoteLine.tenant_id == tenant_id,
                CreditNoteLine.credit_note_id == credit_note_id,
            )
        )
        .scalars()
        .all()
    )
    if not lines:
        raise AccountingValidationError(f"credit note {credit_note_id} needs at least one line.")

    subtotal = sum((line.line_subtotal for line in lines), ZERO)
    tax_total = sum((line.line_tax for line in lines), ZERO)
    total = subtotal + tax_total
    if total <= ZERO:
        raise AccountingValidationError(f"credit note {credit_note_id} total must be positive.")

    # Gapless per-tenant numbering, a genuinely separate sequence from
    # Invoice.invoice_number (module docstring): own advisory-lock key,
    # own "last number" query scoped to CreditNote.tenant_id.
    acquire_tenant_advisory_lock(session, tenant_id, f"accounting.credit_note_number.{tenant_id}")
    last_number = session.execute(
        select(CreditNote.credit_note_number)
        .where(CreditNote.tenant_id == tenant_id, CreditNote.credit_note_number.is_not(None))
        .order_by(CreditNote.credit_note_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    next_number = (last_number or 0) + 1

    # Mirror image of post_invoice()'s own journal shape (module
    # docstring): Dr each line's own account (and aggregated tax account)
    # for the credit amount, Cr the invoice's own receivable account for
    # the total -- reversing revenue recognition and reducing what is
    # owed, for exactly this credit note's own (possibly partial) amount.
    journal_entry_id = uuid.uuid4()
    session.add(
        JournalEntry(
            id=journal_entry_id,
            tenant_id=tenant_id,
            entry_date=row.issue_date,
            currency=row.currency,
            description=f"Credit note {next_number}",
            status=JOURNAL_ENTRY_STATUS_DRAFT,
            created_by_user_id=actor_user_id,
        )
    )
    session.flush()
    tax_by_account: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=line.account_id,
                debit_amount=line.line_subtotal,
                credit_amount=ZERO,
            )
        )
        if line.line_tax > ZERO and line.tax_code_id is not None:
            tax_code = session.get(TaxCode, line.tax_code_id)
            assert tax_code is not None  # validated at create time
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
                debit_amount=amount,
                credit_amount=ZERO,
            )
        )
    session.add(
        JournalLine(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            journal_entry_id=journal_entry_id,
            account_id=invoice.receivable_account_id,
            debit_amount=ZERO,
            credit_amount=total,
        )
    )
    session.flush()

    # Reuses Phase 24's own posting logic completely -- balance
    # enforcement, period resolution, advisory locking, status transition
    # (module docstring: never duplicated).
    post_result = _post_journal_entry_in_session(
        session, tenant_id, journal_entry_id, actor_user_id
    )

    row.credit_note_number = next_number
    row.subtotal = subtotal
    row.tax_total = tax_total
    row.total = total
    row.period_id = uuid.UUID(str(post_result["period_id"]))
    row.journal_entry_id = journal_entry_id
    row.status = DOCUMENT_STATUS_POSTED
    row.posted_by_user_id = actor_user_id
    row.posted_at = datetime.now(UTC)
    session.flush()
    return {
        "credit_note_id": str(credit_note_id),
        "credit_note_number": next_number,
        "journal_entry_id": str(journal_entry_id),
        "period_id": str(post_result["period_id"]),
    }


def post_credit_note(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, credit_note_id: uuid.UUID
) -> CreditNoteView:
    require(actor_user_id, tenant_id, resource=CREDIT_NOTE_RESOURCE, action="post")
    with tenant_session_scope(tenant_id) as session:
        result = _post_credit_note_in_session(session, tenant_id, credit_note_id, actor_user_id)

    view = _load_view(tenant_id, credit_note_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.credit_note.posted",
        resource_type="accounting.credit_note",
        resource_id=str(credit_note_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "credit_note_number": str(result["credit_note_number"]),
            "journal_entry_id": str(result["journal_entry_id"]),
        },
    )
    publish(
        Event(
            type=ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE,
            version=ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "credit_note_id": str(credit_note_id),
                "invoice_id": str(view.invoice_id),
                "journal_entry_id": str(result["journal_entry_id"]),
            },
        )
    )
    return view


__all__ = [
    "ACCOUNTING_CREDIT_NOTE_CREATED_EVENT_TYPE",
    "ACCOUNTING_CREDIT_NOTE_POSTED_EVENT_TYPE",
    "CreditNoteLineInput",
    "CreditNoteLineView",
    "CreditNoteView",
    "create_credit_note",
    "get_credit_note",
    "list_credit_notes_for_invoice",
    "post_credit_note",
    "void_credit_note",
]
