"""Supplier bills (ADR-0014 Decision 12, docs/ROADMAP.md Phase 25) -- the
purchase-side mirror of `invoices.py`, with two deliberate asymmetries:

1. **No gapless internal numbering.** Gapless sequential numbering is a
   legal requirement for invoices a tenant *issues*, never for bills a
   tenant *receives* -- a bill already carries the supplier's own
   `supplier_reference` (Decision 12).
2. **`bill.post` is owner-only** (ADR-0014 Decision 13) -- approving
   outgoing spend is the classic segregation-of-duties control point,
   unlike issuing a sales invoice.

Otherwise identical structure to `invoices.py`, including the same
same-transaction composition with `product/accounting/journal.py`'s
internal posting/reversal helpers -- see that module's own docstring for
the full atomicity reasoning, not repeated here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import run_idempotent
from infra.db import IntegrityError, delete, select, tenant_session_scope

from product.accounting.contacts import _assert_role
from product.accounting.errors import (
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.journal import (
    _post_journal_entry_in_session,
    _reverse_journal_entry_in_session,
)
from product.accounting.models import (
    CONTACT_ROLE_SUPPLIER,
    DOCUMENT_STATUS_CANCELLED,
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_POSTED,
    DOCUMENT_STATUS_VOIDED,
    JOURNAL_ENTRY_STATUS_DRAFT,
    MAX_DOCUMENT_DESCRIPTION_LENGTH,
    MAX_LINE_DESCRIPTION_LENGTH,
    MAX_SUPPLIER_REFERENCE_LENGTH,
    ZERO,
    Account,
    Bill,
    BillLine,
    JournalEntry,
    JournalLine,
    TaxCode,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import BILL_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_BILL_CREATED_EVENT_TYPE = "accounting.bill.created"
ACCOUNTING_BILL_CREATED_EVENT_VERSION = 1
ACCOUNTING_BILL_POSTED_EVENT_TYPE = "accounting.bill.posted"
ACCOUNTING_BILL_POSTED_EVENT_VERSION = 1

_CENTS = Decimal("0.01")


def _round(amount: Decimal) -> Decimal:
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


def _validate_supplier_reference(reference: str) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise AccountingValidationError("supplier_reference must be a non-empty string.")
    if len(reference) > MAX_SUPPLIER_REFERENCE_LENGTH:
        raise AccountingValidationError(
            f"supplier_reference must be at most {MAX_SUPPLIER_REFERENCE_LENGTH} characters."
        )
    return reference.strip()


@dataclass(frozen=True, slots=True)
class BillLineInput:
    account_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_code_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class BillLineView:
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
class BillView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_reference: str
    contact_id: uuid.UUID
    payable_account_id: uuid.UUID
    currency: str
    status: str
    bill_date: date
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
    lines: tuple[BillLineView, ...]


def _line_to_view(line: BillLine) -> BillLineView:
    return BillLineView(
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


def _to_view(row: Bill, lines: list[BillLine]) -> BillView:
    return BillView(
        id=row.id,
        tenant_id=row.tenant_id,
        supplier_reference=row.supplier_reference,
        contact_id=row.contact_id,
        payable_account_id=row.payable_account_id,
        currency=row.currency,
        status=row.status,
        bill_date=row.bill_date.date(),
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
    session, tenant_id: uuid.UUID, line: BillLineInput, *, tax_code_cache: dict[uuid.UUID, TaxCode]
) -> tuple[Decimal, Decimal, Decimal]:
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
    session, tenant_id: uuid.UUID, lines: list[BillLineInput]
) -> list[tuple[BillLineInput, Decimal, Decimal, Decimal]]:
    if not lines:
        raise AccountingValidationError("a bill needs at least one line.")
    tax_code_cache: dict[uuid.UUID, TaxCode] = {}
    validated: list[tuple[BillLineInput, Decimal, Decimal, Decimal]] = []
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


def create_bill(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    supplier_reference: str,
    payable_account_id: uuid.UUID,
    currency: str,
    bill_date: date,
    due_date: date,
    lines: list[BillLineInput],
    description: str | None = None,
    idempotency_key: str | None = None,
) -> BillView:
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="create")
    if due_date < bill_date:
        raise AccountingValidationError("due_date must not be before bill_date.")
    validated_currency = _validate_currency(currency)
    validated_reference = _validate_supplier_reference(supplier_reference)
    validated_description = _validate_description(description) if description else None

    def _business(session) -> dict[str, object]:
        _assert_role(session, tenant_id, contact_id, required_role=CONTACT_ROLE_SUPPLIER)
        validated_lines = _validate_lines(session, tenant_id, lines)
        payable = session.get(Account, payable_account_id)
        if payable is None or payable.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", payable_account_id)

        subtotal = sum((v[1] for v in validated_lines), ZERO)
        tax_total = sum((v[2] for v in validated_lines), ZERO)

        bill_id = uuid.uuid4()
        try:
            session.add(
                Bill(
                    id=bill_id,
                    tenant_id=tenant_id,
                    supplier_reference=validated_reference,
                    contact_id=contact_id,
                    payable_account_id=payable_account_id,
                    currency=validated_currency,
                    status=DOCUMENT_STATUS_DRAFT,
                    bill_date=_date_to_utc_midnight(bill_date),
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
        except IntegrityError as exc:
            raise AccountingConflictError("supplier_reference", validated_reference) from exc
        for line_no, (line, line_subtotal, line_tax, line_total) in enumerate(
            validated_lines, start=1
        ):
            session.add(
                BillLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    bill_id=bill_id,
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
        return {"bill_id": str(bill_id)}

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _business(session)
        is_replay = False
    else:
        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.bill.create",
            idempotency_key,
            fingerprint_payload={
                "contact_id": str(contact_id),
                "supplier_reference": validated_reference,
            },
            business_fn=_business,
        )

    bill_id = uuid.UUID(str(result["bill_id"]))
    view = _load_view(tenant_id, bill_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.bill.created",
            resource_type="accounting.bill",
            resource_id=str(bill_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"contact_id": str(contact_id), "line_count": len(view.lines)},
        )
        publish(
            Event(
                type=ACCOUNTING_BILL_CREATED_EVENT_TYPE,
                version=ACCOUNTING_BILL_CREATED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"bill_id": str(bill_id), "contact_id": str(contact_id)},
            )
        )
    return view


def _load_view(tenant_id: uuid.UUID, bill_id: uuid.UUID) -> BillView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Bill, bill_id)
        assert row is not None
        lines = (
            session.execute(
                select(BillLine)
                .where(BillLine.tenant_id == tenant_id, BillLine.bill_id == bill_id)
                .order_by(BillLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
        session.expunge(row)
        for line in lines:
            session.expunge(line)
    return view


def _get_owned_row(session, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill:
    row = session.get(Bill, bill_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("bill", bill_id)
    return row


def get_bill(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> BillView:
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, bill_id)
        lines = (
            session.execute(
                select(BillLine)
                .where(BillLine.tenant_id == tenant_id, BillLine.bill_id == bill_id)
                .order_by(BillLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
    return view


def list_bills(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[BillView]:
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        query = select(Bill).where(Bill.tenant_id == tenant_id)
        if status is not None:
            query = query.where(Bill.status == status)
        rows = (
            session.execute(
                query.order_by(Bill.due_date.asc()).limit(bounded_limit).offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        views = []
        for row in rows:
            lines = (
                session.execute(
                    select(BillLine)
                    .where(BillLine.tenant_id == tenant_id, BillLine.bill_id == row.id)
                    .order_by(BillLine.line_no.asc())
                )
                .scalars()
                .all()
            )
            views.append(_to_view(row, list(lines)))
    return views


def update_bill(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    *,
    description: str | None = ...,  # type: ignore[assignment]
    lines: list[BillLineInput] | None = None,
) -> BillView:
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, bill_id)
        if row.status != DOCUMENT_STATUS_DRAFT:
            raise AccountingValidationError(
                f"bill {bill_id} cannot be edited while status={row.status!r} "
                "(only 'draft' bills can be)."
            )
        if description is not ...:
            row.description = _validate_description(description) if description else None
        if lines is not None:
            validated_lines = _validate_lines(session, tenant_id, lines)
            session.execute(
                delete(BillLine).where(BillLine.tenant_id == tenant_id, BillLine.bill_id == bill_id)
            )
            session.flush()
            for line_no, (line, line_subtotal, line_tax, line_total) in enumerate(
                validated_lines, start=1
            ):
                session.add(
                    BillLine(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        bill_id=bill_id,
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

    view = _load_view(tenant_id, bill_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bill.updated",
        resource_type="accounting.bill",
        resource_id=str(bill_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"line_count": len(view.lines)},
    )
    return view


def void_bill(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> BillView:
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="void")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Bill, bill_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bill", bill_id)
        if row.status != DOCUMENT_STATUS_DRAFT:
            raise AccountingValidationError(
                f"bill {bill_id} cannot be voided while status={row.status!r} "
                "(only 'draft' bills can be)."
            )
        row.status = DOCUMENT_STATUS_VOIDED
        session.flush()

    view = _load_view(tenant_id, bill_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bill.voided",
        resource_type="accounting.bill",
        resource_id=str(bill_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


def _post_bill_in_session(
    session, tenant_id: uuid.UUID, bill_id: uuid.UUID, actor_user_id: uuid.UUID
) -> dict[str, object]:
    row = session.get(Bill, bill_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("bill", bill_id)
    if row.status != DOCUMENT_STATUS_DRAFT:
        raise AccountingValidationError(
            f"bill {bill_id} cannot be posted while status={row.status!r} "
            "(only 'draft' bills can be)."
        )

    lines = (
        session.execute(
            select(BillLine).where(BillLine.tenant_id == tenant_id, BillLine.bill_id == bill_id)
        )
        .scalars()
        .all()
    )
    if not lines:
        raise AccountingValidationError(f"bill {bill_id} needs at least one line to post.")

    subtotal = sum((line.line_subtotal for line in lines), ZERO)
    tax_total = sum((line.line_tax for line in lines), ZERO)
    total = subtotal + tax_total
    if total <= ZERO:
        raise AccountingValidationError(f"bill {bill_id} total must be positive to post.")

    # No gapless numbering for bills (module docstring) -- straight to
    # journal-entry construction: Cr payable for the full total; Dr each
    # line's own expense account for its line_subtotal; Dr each distinct
    # tax account for its aggregated line_tax (input VAT).
    journal_entry_id = uuid.uuid4()
    session.add(
        JournalEntry(
            id=journal_entry_id,
            tenant_id=tenant_id,
            entry_date=row.bill_date,
            currency=row.currency,
            description=f"Bill {row.supplier_reference}",
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
            account_id=row.payable_account_id,
            debit_amount=ZERO,
            credit_amount=total,
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
                debit_amount=line.line_subtotal,
                credit_amount=ZERO,
            )
        )
        if line.line_tax > ZERO and line.tax_code_id is not None:
            tax_code = session.get(TaxCode, line.tax_code_id)
            assert tax_code is not None
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
    session.flush()

    post_result = _post_journal_entry_in_session(
        session, tenant_id, journal_entry_id, actor_user_id
    )

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
        "bill_id": str(bill_id),
        "journal_entry_id": str(journal_entry_id),
        "period_id": str(post_result["period_id"]),
    }


def post_bill(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> BillView:
    """Owner-only (ADR-0014 Decision 13) -- `require()` below enforces it,
    the deliberate asymmetry with `post_invoice()`."""
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="post")

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _post_bill_in_session(session, tenant_id, bill_id, actor_user_id)
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _post_bill_in_session(session, tenant_id, bill_id, actor_user_id)

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.bill.post",
            idempotency_key,
            fingerprint_payload={"bill_id": str(bill_id)},
            business_fn=_business,
        )

    view = _load_view(tenant_id, bill_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.bill.posted",
            resource_type="accounting.bill",
            resource_id=str(bill_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"journal_entry_id": str(result["journal_entry_id"])},
        )
        publish(
            Event(
                type=ACCOUNTING_BILL_POSTED_EVENT_TYPE,
                version=ACCOUNTING_BILL_POSTED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={
                    "bill_id": str(bill_id),
                    "contact_id": str(view.contact_id),
                    "journal_entry_id": str(result["journal_entry_id"]),
                },
            )
        )
    return view


def cancel_bill(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    *,
    cancellation_date: date | None = None,
) -> BillView:
    """`posted -> cancelled`, owner-only, mirrors `invoices.py
    ::cancel_invoice()` exactly."""
    require(actor_user_id, tenant_id, resource=BILL_RESOURCE, action="cancel")
    resolved_date = cancellation_date if cancellation_date is not None else datetime.now(UTC).date()

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Bill, bill_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bill", bill_id)
        if row.status != DOCUMENT_STATUS_POSTED:
            raise AccountingValidationError(
                f"bill {bill_id} cannot be cancelled while status={row.status!r} "
                "(only 'posted' bills can be)."
            )
        assert row.journal_entry_id is not None
        _reverse_journal_entry_in_session(
            session,
            tenant_id,
            row.journal_entry_id,
            actor_user_id,
            resolved_date,
            f"Cancellation of bill {row.supplier_reference}",
        )
        row.status = DOCUMENT_STATUS_CANCELLED
        row.outstanding_amount = ZERO
        session.flush()

    view = _load_view(tenant_id, bill_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bill.cancelled",
        resource_type="accounting.bill",
        resource_id=str(bill_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


__all__ = [
    "ACCOUNTING_BILL_CREATED_EVENT_TYPE",
    "ACCOUNTING_BILL_POSTED_EVENT_TYPE",
    "BillLineInput",
    "BillLineView",
    "BillView",
    "cancel_bill",
    "create_bill",
    "get_bill",
    "list_bills",
    "post_bill",
    "update_bill",
    "void_bill",
]
