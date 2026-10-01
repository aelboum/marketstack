"""The Accounting API (docs/ROADMAP.md Phase 24/25/15.3/15.5 service
layer, exposed over HTTP), mounted under `/v1/accounting` in
`product/api/main.py`.

**History**: this module began as a single, deliberately minimal route --
a tenant's overdue customer invoices, the one accounting condition the
Phase 25 Definition of Done required a real Command Center consumer for
(`frontend/components/today/AttentionSection.tsx`'s `OverdueInvoicesLine`).
The Accounting API exposure phase (the prerequisite for UI-15) extends it
to every already-implemented, already-tested service operation. The
overdue route's path and response shape are unchanged, and it is declared
first so `/invoices/overdue` is never shadowed by `/invoices/{invoice_id}`.

**Thin adapters only**: every route calls exactly one existing
`product/accounting/*.py` service function. Each of those performs its
own `product.accounting.permissions.require()` check (a `core.rbac.can()`
call against the path's `tenant_id`) before any database access, plus its
own audit logging, idempotency, and period-locking -- none of which is
duplicated here. The path `tenant_id` is therefore never an authorization
input by itself: an actor holding no matching permission in that tenant
gets the same non-enumerating 404 as an unknown id.

**Ingress dependency choice / non-enumeration**: identical reasoning to
`product/billing/routes.py`/`product/approvals/routes.py` -- every route
uses `api.dependencies.get_current_actor`. `AccountingAccessDeniedError`,
`AccountingReferenceNotFoundError`, and `product.crm`'s own access-denied/
not-found errors (raised when a contact id is checked through
`product.crm.contacts.get_contact()`) all map to the identical `404`.
`AccountingValidationError` and an invalid idempotency key map to `400`;
`AccountingConflictError`, a missing/closed accounting period, and a
reused/in-flight idempotency key map to `409`, each with a fixed message
that never echoes internal identifiers.

**API-level limits** (the only validation this module adds on top of the
service layer, both purely defensive): a document/journal line list is
capped at `MAX_LINES_PER_DOCUMENT`, and an imported bank-statement CSV at
`MAX_STATEMENT_CSV_LENGTH` characters -- neither service function bounds
its own input size, and an unbounded request body is not safe to accept
over HTTP.

**Deliberately not exposed**: `periods.find_period_for_date()` (an
internal, session-scoped helper for `journal.py`, not an operation).
Nothing else in the service layer is withheld.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from api.dependencies import get_current_actor
from api.errors import not_found
from core.idempotency import (
    IdempotencyInProgressError,
    IdempotencyKeyInvalidError,
    IdempotencyKeyReusedError,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from product.accounting.accounts import (
    AccountView,
    create_account,
    deactivate_account,
    get_account,
    list_accounts,
    reactivate_account,
    update_account,
)
from product.accounting.banking import (
    BankAccountView,
    BankStatementLineView,
    BankStatementView,
    MatchCandidate,
    assign_line_to_account,
    confirm_match_to_document,
    create_bank_account,
    get_bank_account,
    import_bank_statement_csv,
    list_bank_accounts,
    list_bank_statement_lines,
    suggest_matches,
)
from product.accounting.bills import (
    BillLineInput,
    BillView,
    cancel_bill,
    create_bill,
    get_bill,
    list_bills,
    post_bill,
    update_bill,
    void_bill,
)
from product.accounting.contacts import (
    ContactProfileView,
    get_contact_role,
    list_contact_roles,
    tag_contact_role,
    update_contact_role,
)
from product.accounting.credit_notes import (
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
    AccountingConflictError,
    AccountingPeriodClosedError,
    AccountingPeriodNotFoundError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.invoices import (
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
from product.accounting.journal import (
    JournalEntryView,
    JournalLineInput,
    create_journal_entry,
    get_journal_entry,
    list_journal_entries,
    post_journal_entry,
    reverse_journal_entry,
    update_journal_entry,
    void_journal_entry,
)
from product.accounting.models import (
    ALLOCATION_DOCUMENT_TYPE_BILL,
    ALLOCATION_DOCUMENT_TYPE_INVOICE,
    MAX_ACCOUNT_CODE_LENGTH,
    MAX_ACCOUNT_NAME_LENGTH,
    MAX_BANK_ACCOUNT_NAME_LENGTH,
    MAX_BANK_STATEMENT_REFERENCE_LENGTH,
    MAX_DOCUMENT_DESCRIPTION_LENGTH,
    MAX_IBAN_LENGTH,
    MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH,
    MAX_LINE_DESCRIPTION_LENGTH,
    MAX_PAYMENT_REFERENCE_LENGTH,
    MAX_SUPPLIER_REFERENCE_LENGTH,
    MAX_TAX_CODE_LENGTH,
    MAX_TAX_NAME_LENGTH,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE
from product.accounting.payments import (
    PaymentAllocationView,
    PaymentView,
    create_allocation,
    create_payment,
    get_payment,
    list_allocations_for_document,
    list_payments,
    reverse_allocation,
)
from product.accounting.periods import (
    PeriodView,
    close_period,
    create_period,
    get_period,
    list_periods,
    reopen_period,
)
from product.accounting.tax_codes import (
    TaxCodeView,
    create_tax_code,
    deactivate_tax_code,
    get_tax_code,
    list_tax_codes,
)
from product.crm.errors import (
    CrmAccessDeniedError,
    CrmReferenceNotFoundError,
    CrmValidationError,
)

router = APIRouter(prefix="/v1/accounting", tags=["accounting"])

MAX_LINES_PER_DOCUMENT = 500
MAX_STATEMENT_CSV_LENGTH = 1_000_000
MAX_IDEMPOTENCY_KEY_LENGTH = 200

_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    AccountingValidationError,
    CrmValidationError,
    IdempotencyKeyInvalidError,
)
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    AccountingAccessDeniedError,
    AccountingReferenceNotFoundError,
    CrmAccessDeniedError,
    CrmReferenceNotFoundError,
)
_CONFLICT_MESSAGES: tuple[tuple[type[Exception], str], ...] = (
    (AccountingConflictError, "That accounting record conflicts with an existing one."),
    (AccountingPeriodNotFoundError, "No accounting period covers that date."),
    (AccountingPeriodClosedError, "The accounting period covering that date is closed."),
    (
        IdempotencyKeyReusedError,
        "That idempotency key was already used for a different request.",
    ),
    (IdempotencyInProgressError, "A request with that idempotency key is still in progress."),
)
_CONFLICT_ERRORS: tuple[type[Exception], ...] = tuple(exc for exc, _ in _CONFLICT_MESSAGES)


def _conflict_detail(exc: Exception) -> str:
    for exc_type, message in _CONFLICT_MESSAGES:
        if isinstance(exc, exc_type):
            return message
    return "That accounting operation conflicts with the tenant's current state."


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail(exc)
        ) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


def _money(value: Decimal) -> str:
    return str(value)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid_str(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _description_kwargs(description: str | None, clear_description: bool) -> dict[str, object]:
    """Mirrors `product/billing/routes.py::update_resale_plan_route()`'s
    own "omitted vs. explicit null" disambiguation -- the service layer's
    own `description=...` sentinel means "leave unchanged"."""
    if clear_description:
        return {"description": None}
    if description is not None:
        return {"description": description}
    return {}


# --- Request bodies ----------------------------------------------------------


class _IdempotentRequest(BaseModel):
    idempotency_key: str | None = Field(
        default=None, min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH
    )


class CreateAccountRequest(BaseModel):
    code: str = Field(max_length=MAX_ACCOUNT_CODE_LENGTH)
    name: str = Field(max_length=MAX_ACCOUNT_NAME_LENGTH)
    account_type: str


class UpdateAccountRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_ACCOUNT_NAME_LENGTH)


class CreatePeriodRequest(BaseModel):
    start_date: date
    end_date: date


class JournalLineRequest(BaseModel):
    account_id: uuid.UUID
    debit_amount: Decimal = Decimal("0")
    credit_amount: Decimal = Decimal("0")

    def to_input(self) -> JournalLineInput:
        return JournalLineInput(
            account_id=self.account_id,
            debit_amount=self.debit_amount,
            credit_amount=self.credit_amount,
        )


class CreateJournalEntryRequest(BaseModel):
    entry_date: date
    currency: str
    lines: list[JournalLineRequest] = Field(max_length=MAX_LINES_PER_DOCUMENT)
    description: str | None = Field(default=None, max_length=MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH)


class UpdateJournalEntryRequest(BaseModel):
    description: str | None = Field(default=None, max_length=MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH)
    clear_description: bool = False
    lines: list[JournalLineRequest] | None = Field(default=None, max_length=MAX_LINES_PER_DOCUMENT)


class PostRequest(_IdempotentRequest):
    pass


class ReverseJournalEntryRequest(_IdempotentRequest):
    reversal_entry_date: date | None = None
    description: str | None = Field(default=None, max_length=MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH)


class CreateTaxCodeRequest(BaseModel):
    code: str = Field(max_length=MAX_TAX_CODE_LENGTH)
    name: str = Field(max_length=MAX_TAX_NAME_LENGTH)
    rate_percent: Decimal
    tax_type: str
    tax_account_id: uuid.UUID
    effective_from: date | None = None
    effective_to: date | None = None


class TagContactRoleRequest(BaseModel):
    contact_id: uuid.UUID
    role: str


class UpdateContactRoleRequest(BaseModel):
    role: str


class DocumentLineRequest(BaseModel):
    account_id: uuid.UUID
    description: str = Field(max_length=MAX_LINE_DESCRIPTION_LENGTH)
    quantity: Decimal
    unit_price: Decimal
    tax_code_id: uuid.UUID | None = None


class CreateInvoiceRequest(_IdempotentRequest):
    contact_id: uuid.UUID
    receivable_account_id: uuid.UUID
    currency: str
    issue_date: date
    due_date: date
    lines: list[DocumentLineRequest] = Field(max_length=MAX_LINES_PER_DOCUMENT)
    description: str | None = Field(default=None, max_length=MAX_DOCUMENT_DESCRIPTION_LENGTH)


class UpdateInvoiceRequest(BaseModel):
    description: str | None = Field(default=None, max_length=MAX_DOCUMENT_DESCRIPTION_LENGTH)
    clear_description: bool = False
    lines: list[DocumentLineRequest] | None = Field(default=None, max_length=MAX_LINES_PER_DOCUMENT)
    due_date: date | None = None


class CancelDocumentRequest(BaseModel):
    cancellation_date: date | None = None


class CreateBillRequest(_IdempotentRequest):
    contact_id: uuid.UUID
    supplier_reference: str = Field(max_length=MAX_SUPPLIER_REFERENCE_LENGTH)
    payable_account_id: uuid.UUID
    currency: str
    bill_date: date
    due_date: date
    lines: list[DocumentLineRequest] = Field(max_length=MAX_LINES_PER_DOCUMENT)
    description: str | None = Field(default=None, max_length=MAX_DOCUMENT_DESCRIPTION_LENGTH)


class UpdateBillRequest(BaseModel):
    description: str | None = Field(default=None, max_length=MAX_DOCUMENT_DESCRIPTION_LENGTH)
    clear_description: bool = False
    lines: list[DocumentLineRequest] | None = Field(default=None, max_length=MAX_LINES_PER_DOCUMENT)


class CreatePaymentRequest(_IdempotentRequest):
    contact_id: uuid.UUID
    direction: str
    amount: Decimal
    currency: str
    reference: str | None = Field(default=None, max_length=MAX_PAYMENT_REFERENCE_LENGTH)


class CreateAllocationRequest(_IdempotentRequest):
    document_type: str
    document_id: uuid.UUID
    amount: Decimal


class CreateCreditNoteRequest(BaseModel):
    currency: str
    issue_date: date
    lines: list[DocumentLineRequest] = Field(max_length=MAX_LINES_PER_DOCUMENT)
    description: str | None = Field(default=None, max_length=MAX_DOCUMENT_DESCRIPTION_LENGTH)


class CreateBankAccountRequest(BaseModel):
    ledger_account_id: uuid.UUID
    name: str = Field(max_length=MAX_BANK_ACCOUNT_NAME_LENGTH)
    currency: str
    iban: str | None = Field(default=None, max_length=MAX_IBAN_LENGTH)


class ImportBankStatementRequest(BaseModel):
    csv_text: str = Field(max_length=MAX_STATEMENT_CSV_LENGTH)
    period_start_date: date
    period_end_date: date
    reference: str | None = Field(default=None, max_length=MAX_BANK_STATEMENT_REFERENCE_LENGTH)


class ConfirmMatchRequest(BaseModel):
    document_type: str
    document_id: uuid.UUID


class AssignLineToAccountRequest(BaseModel):
    account_id: uuid.UUID


def _invoice_lines(lines: list[DocumentLineRequest]) -> list[InvoiceLineInput]:
    return [
        InvoiceLineInput(
            account_id=line.account_id,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            tax_code_id=line.tax_code_id,
        )
        for line in lines
    ]


def _bill_lines(lines: list[DocumentLineRequest]) -> list[BillLineInput]:
    return [
        BillLineInput(
            account_id=line.account_id,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            tax_code_id=line.tax_code_id,
        )
        for line in lines
    ]


def _credit_note_lines(lines: list[DocumentLineRequest]) -> list[CreditNoteLineInput]:
    return [
        CreditNoteLineInput(
            account_id=line.account_id,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            tax_code_id=line.tax_code_id,
        )
        for line in lines
    ]


# --- Serialization -------------------------------------------------------------


def _invoice_summary_dict(view: InvoiceView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "invoice_number": view.invoice_number,
        "contact_id": str(view.contact_id),
        "currency": view.currency,
        "status": view.status,
        "due_date": view.due_date.isoformat(),
        "total": str(view.total),
        "outstanding_amount": str(view.outstanding_amount),
    }


def _account_dict(view: AccountView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "code": view.code,
        "name": view.name,
        "account_type": view.account_type,
        "is_active": view.is_active,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _period_dict(view: PeriodView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "start_date": view.start_date.isoformat(),
        "end_date": view.end_date.isoformat(),
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _journal_entry_dict(view: JournalEntryView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "entry_date": view.entry_date.isoformat(),
        "currency": view.currency,
        "description": view.description,
        "status": view.status,
        "period_id": _uuid_str(view.period_id),
        "reverses_entry_id": _uuid_str(view.reverses_entry_id),
        "created_by_user_id": str(view.created_by_user_id),
        "posted_by_user_id": _uuid_str(view.posted_by_user_id),
        "posted_at": _iso(view.posted_at),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
        "lines": [
            {
                "id": str(line.id),
                "account_id": str(line.account_id),
                "debit_amount": _money(line.debit_amount),
                "credit_amount": _money(line.credit_amount),
            }
            for line in view.lines
        ],
    }


def _tax_code_dict(view: TaxCodeView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "code": view.code,
        "name": view.name,
        "rate_percent": _money(view.rate_percent),
        "tax_type": view.tax_type,
        "tax_account_id": str(view.tax_account_id),
        "is_active": view.is_active,
        "effective_from": _iso(view.effective_from),
        "effective_to": _iso(view.effective_to),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _contact_profile_dict(view: ContactProfileView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id),
        "role": view.role,
        "created_at": view.created_at.isoformat(),
    }


def _document_line_dict(line) -> dict[str, object]:
    return {
        "id": str(line.id),
        "account_id": str(line.account_id),
        "description": line.description,
        "quantity": _money(line.quantity),
        "unit_price": _money(line.unit_price),
        "tax_code_id": _uuid_str(line.tax_code_id),
        "line_subtotal": _money(line.line_subtotal),
        "line_tax": _money(line.line_tax),
        "line_total": _money(line.line_total),
    }


def _invoice_dict(view: InvoiceView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "invoice_number": view.invoice_number,
        "contact_id": str(view.contact_id),
        "receivable_account_id": str(view.receivable_account_id),
        "currency": view.currency,
        "status": view.status,
        "issue_date": view.issue_date.isoformat(),
        "due_date": view.due_date.isoformat(),
        "subtotal": _money(view.subtotal),
        "tax_total": _money(view.tax_total),
        "total": _money(view.total),
        "outstanding_amount": _money(view.outstanding_amount),
        "period_id": _uuid_str(view.period_id),
        "journal_entry_id": _uuid_str(view.journal_entry_id),
        "description": view.description,
        "created_by_user_id": str(view.created_by_user_id),
        "posted_by_user_id": _uuid_str(view.posted_by_user_id),
        "posted_at": _iso(view.posted_at),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
        "lines": [_document_line_dict(line) for line in view.lines],
    }


def _bill_dict(view: BillView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "supplier_reference": view.supplier_reference,
        "contact_id": str(view.contact_id),
        "payable_account_id": str(view.payable_account_id),
        "currency": view.currency,
        "status": view.status,
        "bill_date": view.bill_date.isoformat(),
        "due_date": view.due_date.isoformat(),
        "subtotal": _money(view.subtotal),
        "tax_total": _money(view.tax_total),
        "total": _money(view.total),
        "outstanding_amount": _money(view.outstanding_amount),
        "period_id": _uuid_str(view.period_id),
        "journal_entry_id": _uuid_str(view.journal_entry_id),
        "description": view.description,
        "created_by_user_id": str(view.created_by_user_id),
        "posted_by_user_id": _uuid_str(view.posted_by_user_id),
        "posted_at": _iso(view.posted_at),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
        "lines": [_document_line_dict(line) for line in view.lines],
    }


def _payment_dict(view: PaymentView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "contact_id": str(view.contact_id),
        "direction": view.direction,
        "amount": _money(view.amount),
        "currency": view.currency,
        "unallocated_amount": _money(view.unallocated_amount),
        "reference": view.reference,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _allocation_dict(view: PaymentAllocationView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "payment_id": str(view.payment_id),
        "document_type": view.document_type,
        "document_id": str(view.document_id),
        "amount": _money(view.amount),
        "reverses_allocation_id": _uuid_str(view.reverses_allocation_id),
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
    }


def _credit_note_dict(view: CreditNoteView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "credit_note_number": view.credit_note_number,
        "invoice_id": str(view.invoice_id),
        "currency": view.currency,
        "status": view.status,
        "issue_date": view.issue_date.isoformat(),
        "subtotal": _money(view.subtotal),
        "tax_total": _money(view.tax_total),
        "total": _money(view.total),
        "period_id": _uuid_str(view.period_id),
        "journal_entry_id": _uuid_str(view.journal_entry_id),
        "description": view.description,
        "created_by_user_id": str(view.created_by_user_id),
        "posted_by_user_id": _uuid_str(view.posted_by_user_id),
        "posted_at": _iso(view.posted_at),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
        "lines": [_document_line_dict(line) for line in view.lines],
    }


def _bank_account_dict(view: BankAccountView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "ledger_account_id": str(view.ledger_account_id),
        "name": view.name,
        "iban": view.iban,
        "currency": view.currency,
        "created_at": view.created_at.isoformat(),
    }


def _bank_statement_line_dict(view: BankStatementLineView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "bank_statement_id": str(view.bank_statement_id),
        "bank_account_id": str(view.bank_account_id),
        "line_no": view.line_no,
        "transaction_date": view.transaction_date.isoformat(),
        "amount": _money(view.amount),
        "description": view.description,
        "counterparty_reference": view.counterparty_reference,
        "status": view.status,
        "matched_document_type": view.matched_document_type,
        "matched_document_id": _uuid_str(view.matched_document_id),
        "matched_payment_id": _uuid_str(view.matched_payment_id),
        "matched_account_id": _uuid_str(view.matched_account_id),
        "journal_entry_id": _uuid_str(view.journal_entry_id),
        "reconciled_by_user_id": _uuid_str(view.reconciled_by_user_id),
        "reconciled_at": _iso(view.reconciled_at),
        "created_at": view.created_at.isoformat(),
    }


def _bank_statement_dict(view: BankStatementView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "bank_account_id": str(view.bank_account_id),
        "reference": view.reference,
        "period_start_date": view.period_start_date.isoformat(),
        "period_end_date": view.period_end_date.isoformat(),
        "imported_by_user_id": str(view.imported_by_user_id),
        "imported_at": view.imported_at.isoformat(),
        "imported_line_count": view.imported_line_count,
        "duplicate_line_count": view.duplicate_line_count,
        "lines": [_bank_statement_line_dict(line) for line in view.lines],
    }


def _match_candidate_dict(candidate: MatchCandidate) -> dict[str, object]:
    return {
        "document_type": candidate.document_type,
        "document_id": str(candidate.document_id),
        "outstanding_amount": _money(candidate.outstanding_amount),
        "contact_id": str(candidate.contact_id),
        "reference_date": candidate.reference_date.isoformat(),
    }


# --- Customer invoices: overdue (the original Phase 25 route, unchanged) --------
# Declared before `/invoices/{invoice_id}` so the literal `overdue` segment
# is matched first rather than rejected as an invalid invoice id.


@router.get("/tenants/{tenant_id}/invoices/overdue")
def list_overdue_invoices_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    try:
        views = list_invoices(actor_id, tenant_id, overdue_only=True)
    except AccountingAccessDeniedError:
        raise not_found("resource") from None
    return [_invoice_summary_dict(v) for v in views]


# --- Chart of accounts ------------------------------------------------------------


@router.post("/tenants/{tenant_id}/accounts", status_code=status.HTTP_201_CREATED)
def create_account_route(
    tenant_id: uuid.UUID,
    body: CreateAccountRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _account_dict(
        _call(
            create_account,
            actor_id,
            tenant_id,
            code=body.code,
            name=body.name,
            account_type=body.account_type,
        )
    )


@router.get("/tenants/{tenant_id}/accounts")
def list_accounts_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _account_dict(v)
        for v in _call(list_accounts, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/accounts/{account_id}")
def get_account_route(
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _account_dict(_call(get_account, actor_id, tenant_id, account_id))


@router.patch("/tenants/{tenant_id}/accounts/{account_id}")
def update_account_route(
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    body: UpdateAccountRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _account_dict(_call(update_account, actor_id, tenant_id, account_id, name=body.name))


@router.post("/tenants/{tenant_id}/accounts/{account_id}/deactivate")
def deactivate_account_route(
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _account_dict(_call(deactivate_account, actor_id, tenant_id, account_id))


@router.post("/tenants/{tenant_id}/accounts/{account_id}/reactivate")
def reactivate_account_route(
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _account_dict(_call(reactivate_account, actor_id, tenant_id, account_id))


# --- Periods ----------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/periods", status_code=status.HTTP_201_CREATED)
def create_period_route(
    tenant_id: uuid.UUID,
    body: CreatePeriodRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _period_dict(
        _call(
            create_period, actor_id, tenant_id, start_date=body.start_date, end_date=body.end_date
        )
    )


@router.get("/tenants/{tenant_id}/periods")
def list_periods_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _period_dict(v)
        for v in _call(list_periods, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/periods/{period_id}")
def get_period_route(
    tenant_id: uuid.UUID,
    period_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _period_dict(_call(get_period, actor_id, tenant_id, period_id))


@router.post("/tenants/{tenant_id}/periods/{period_id}/close")
def close_period_route(
    tenant_id: uuid.UUID,
    period_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _period_dict(_call(close_period, actor_id, tenant_id, period_id))


@router.post("/tenants/{tenant_id}/periods/{period_id}/reopen")
def reopen_period_route(
    tenant_id: uuid.UUID,
    period_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _period_dict(_call(reopen_period, actor_id, tenant_id, period_id))


# --- Journal entries ---------------------------------------------------------------


@router.post("/tenants/{tenant_id}/journal-entries", status_code=status.HTTP_201_CREATED)
def create_journal_entry_route(
    tenant_id: uuid.UUID,
    body: CreateJournalEntryRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _journal_entry_dict(
        _call(
            create_journal_entry,
            actor_id,
            tenant_id,
            entry_date=body.entry_date,
            currency=body.currency,
            lines=[line.to_input() for line in body.lines],
            description=body.description,
        )
    )


@router.get("/tenants/{tenant_id}/journal-entries")
def list_journal_entries_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _journal_entry_dict(v)
        for v in _call(list_journal_entries, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/journal-entries/{entry_id}")
def get_journal_entry_route(
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _journal_entry_dict(_call(get_journal_entry, actor_id, tenant_id, entry_id))


@router.patch("/tenants/{tenant_id}/journal-entries/{entry_id}")
def update_journal_entry_route(
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: UpdateJournalEntryRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    kwargs = _description_kwargs(body.description, body.clear_description)
    if body.lines is not None:
        kwargs["lines"] = [line.to_input() for line in body.lines]
    return _journal_entry_dict(_call(update_journal_entry, actor_id, tenant_id, entry_id, **kwargs))


@router.post("/tenants/{tenant_id}/journal-entries/{entry_id}/void")
def void_journal_entry_route(
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _journal_entry_dict(_call(void_journal_entry, actor_id, tenant_id, entry_id))


@router.post("/tenants/{tenant_id}/journal-entries/{entry_id}/post")
def post_journal_entry_route(
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: PostRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _journal_entry_dict(
        _call(
            post_journal_entry,
            actor_id,
            tenant_id,
            entry_id,
            idempotency_key=body.idempotency_key if body else None,
        )
    )


@router.post("/tenants/{tenant_id}/journal-entries/{entry_id}/reverse")
def reverse_journal_entry_route(
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: ReverseJournalEntryRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    body = body or ReverseJournalEntryRequest()
    return _journal_entry_dict(
        _call(
            reverse_journal_entry,
            actor_id,
            tenant_id,
            entry_id,
            reversal_entry_date=body.reversal_entry_date,
            description=body.description,
            idempotency_key=body.idempotency_key,
        )
    )


# --- Tax codes ----------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/tax-codes", status_code=status.HTTP_201_CREATED)
def create_tax_code_route(
    tenant_id: uuid.UUID,
    body: CreateTaxCodeRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _tax_code_dict(
        _call(
            create_tax_code,
            actor_id,
            tenant_id,
            code=body.code,
            name=body.name,
            rate_percent=body.rate_percent,
            tax_type=body.tax_type,
            tax_account_id=body.tax_account_id,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
        )
    )


@router.get("/tenants/{tenant_id}/tax-codes")
def list_tax_codes_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _tax_code_dict(v)
        for v in _call(list_tax_codes, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/tax-codes/{tax_code_id}")
def get_tax_code_route(
    tenant_id: uuid.UUID,
    tax_code_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _tax_code_dict(_call(get_tax_code, actor_id, tenant_id, tax_code_id))


@router.post("/tenants/{tenant_id}/tax-codes/{tax_code_id}/deactivate")
def deactivate_tax_code_route(
    tenant_id: uuid.UUID,
    tax_code_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _tax_code_dict(_call(deactivate_tax_code, actor_id, tenant_id, tax_code_id))


# --- Contact roles (customer/supplier tagging -- an invoicing prerequisite) -------


@router.post("/tenants/{tenant_id}/contact-roles", status_code=status.HTTP_201_CREATED)
def tag_contact_role_route(
    tenant_id: uuid.UUID,
    body: TagContactRoleRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _contact_profile_dict(
        _call(tag_contact_role, actor_id, tenant_id, body.contact_id, role=body.role)
    )


@router.get("/tenants/{tenant_id}/contact-roles")
def list_contact_roles_route(
    tenant_id: uuid.UUID,
    role: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _contact_profile_dict(v)
        for v in _call(
            list_contact_roles, actor_id, tenant_id, role=role, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/contact-roles/{contact_id}")
def get_contact_role_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _contact_profile_dict(_call(get_contact_role, actor_id, tenant_id, contact_id))


@router.patch("/tenants/{tenant_id}/contact-roles/{contact_id}")
def update_contact_role_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: UpdateContactRoleRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _contact_profile_dict(
        _call(update_contact_role, actor_id, tenant_id, contact_id, role=body.role)
    )


# --- Customer invoices -----------------------------------------------------------------


@router.post("/tenants/{tenant_id}/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice_route(
    tenant_id: uuid.UUID,
    body: CreateInvoiceRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _invoice_dict(
        _call(
            create_invoice,
            actor_id,
            tenant_id,
            contact_id=body.contact_id,
            receivable_account_id=body.receivable_account_id,
            currency=body.currency,
            issue_date=body.issue_date,
            due_date=body.due_date,
            lines=_invoice_lines(body.lines),
            description=body.description,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/invoices")
def list_invoices_route(
    tenant_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _invoice_dict(v)
        for v in _call(
            list_invoices, actor_id, tenant_id, status=status_filter, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/invoices/{invoice_id}")
def get_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _invoice_dict(_call(get_invoice, actor_id, tenant_id, invoice_id))


@router.patch("/tenants/{tenant_id}/invoices/{invoice_id}")
def update_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: UpdateInvoiceRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    kwargs = _description_kwargs(body.description, body.clear_description)
    if body.lines is not None:
        kwargs["lines"] = _invoice_lines(body.lines)
    if body.due_date is not None:
        kwargs["due_date"] = body.due_date
    return _invoice_dict(_call(update_invoice, actor_id, tenant_id, invoice_id, **kwargs))


@router.post("/tenants/{tenant_id}/invoices/{invoice_id}/void")
def void_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _invoice_dict(_call(void_invoice, actor_id, tenant_id, invoice_id))


@router.post("/tenants/{tenant_id}/invoices/{invoice_id}/post")
def post_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: PostRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _invoice_dict(
        _call(
            post_invoice,
            actor_id,
            tenant_id,
            invoice_id,
            idempotency_key=body.idempotency_key if body else None,
        )
    )


@router.post("/tenants/{tenant_id}/invoices/{invoice_id}/cancel")
def cancel_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: CancelDocumentRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _invoice_dict(
        _call(
            cancel_invoice,
            actor_id,
            tenant_id,
            invoice_id,
            cancellation_date=body.cancellation_date if body else None,
        )
    )


@router.get("/tenants/{tenant_id}/invoices/{invoice_id}/allocations")
def list_invoice_allocations_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _allocation_dict(v)
        for v in _call(
            list_allocations_for_document,
            actor_id,
            tenant_id,
            document_type=ALLOCATION_DOCUMENT_TYPE_INVOICE,
            document_id=invoice_id,
            limit=limit,
            offset=offset,
        )
    ]


# --- Credit notes (always against an existing invoice) ------------------------------


@router.post(
    "/tenants/{tenant_id}/invoices/{invoice_id}/credit-notes",
    status_code=status.HTTP_201_CREATED,
)
def create_credit_note_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: CreateCreditNoteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _credit_note_dict(
        _call(
            create_credit_note,
            actor_id,
            tenant_id,
            invoice_id=invoice_id,
            currency=body.currency,
            issue_date=body.issue_date,
            lines=_credit_note_lines(body.lines),
            description=body.description,
        )
    )


@router.get("/tenants/{tenant_id}/invoices/{invoice_id}/credit-notes")
def list_credit_notes_for_invoice_route(
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _credit_note_dict(v)
        for v in _call(
            list_credit_notes_for_invoice,
            actor_id,
            tenant_id,
            invoice_id,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/tenants/{tenant_id}/credit-notes/{credit_note_id}")
def get_credit_note_route(
    tenant_id: uuid.UUID,
    credit_note_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _credit_note_dict(_call(get_credit_note, actor_id, tenant_id, credit_note_id))


@router.post("/tenants/{tenant_id}/credit-notes/{credit_note_id}/void")
def void_credit_note_route(
    tenant_id: uuid.UUID,
    credit_note_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _credit_note_dict(_call(void_credit_note, actor_id, tenant_id, credit_note_id))


@router.post("/tenants/{tenant_id}/credit-notes/{credit_note_id}/post")
def post_credit_note_route(
    tenant_id: uuid.UUID,
    credit_note_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _credit_note_dict(_call(post_credit_note, actor_id, tenant_id, credit_note_id))


# --- Bills --------------------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/bills", status_code=status.HTTP_201_CREATED)
def create_bill_route(
    tenant_id: uuid.UUID,
    body: CreateBillRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bill_dict(
        _call(
            create_bill,
            actor_id,
            tenant_id,
            contact_id=body.contact_id,
            supplier_reference=body.supplier_reference,
            payable_account_id=body.payable_account_id,
            currency=body.currency,
            bill_date=body.bill_date,
            due_date=body.due_date,
            lines=_bill_lines(body.lines),
            description=body.description,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/bills")
def list_bills_route(
    tenant_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _bill_dict(v)
        for v in _call(
            list_bills, actor_id, tenant_id, status=status_filter, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/bills/{bill_id}")
def get_bill_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bill_dict(_call(get_bill, actor_id, tenant_id, bill_id))


@router.patch("/tenants/{tenant_id}/bills/{bill_id}")
def update_bill_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    body: UpdateBillRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    kwargs = _description_kwargs(body.description, body.clear_description)
    if body.lines is not None:
        kwargs["lines"] = _bill_lines(body.lines)
    return _bill_dict(_call(update_bill, actor_id, tenant_id, bill_id, **kwargs))


@router.post("/tenants/{tenant_id}/bills/{bill_id}/void")
def void_bill_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bill_dict(_call(void_bill, actor_id, tenant_id, bill_id))


@router.post("/tenants/{tenant_id}/bills/{bill_id}/post")
def post_bill_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    body: PostRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bill_dict(
        _call(
            post_bill,
            actor_id,
            tenant_id,
            bill_id,
            idempotency_key=body.idempotency_key if body else None,
        )
    )


@router.post("/tenants/{tenant_id}/bills/{bill_id}/cancel")
def cancel_bill_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    body: CancelDocumentRequest | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bill_dict(
        _call(
            cancel_bill,
            actor_id,
            tenant_id,
            bill_id,
            cancellation_date=body.cancellation_date if body else None,
        )
    )


@router.get("/tenants/{tenant_id}/bills/{bill_id}/allocations")
def list_bill_allocations_route(
    tenant_id: uuid.UUID,
    bill_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _allocation_dict(v)
        for v in _call(
            list_allocations_for_document,
            actor_id,
            tenant_id,
            document_type=ALLOCATION_DOCUMENT_TYPE_BILL,
            document_id=bill_id,
            limit=limit,
            offset=offset,
        )
    ]


# --- Payments and allocations ---------------------------------------------------------


@router.post("/tenants/{tenant_id}/payments", status_code=status.HTTP_201_CREATED)
def create_payment_route(
    tenant_id: uuid.UUID,
    body: CreatePaymentRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _payment_dict(
        _call(
            create_payment,
            actor_id,
            tenant_id,
            contact_id=body.contact_id,
            direction=body.direction,
            amount=body.amount,
            currency=body.currency,
            reference=body.reference,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/payments")
def list_payments_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _payment_dict(v)
        for v in _call(list_payments, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/payments/{payment_id}")
def get_payment_route(
    tenant_id: uuid.UUID,
    payment_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _payment_dict(_call(get_payment, actor_id, tenant_id, payment_id))


@router.post(
    "/tenants/{tenant_id}/payments/{payment_id}/allocations",
    status_code=status.HTTP_201_CREATED,
)
def create_allocation_route(
    tenant_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: CreateAllocationRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _allocation_dict(
        _call(
            create_allocation,
            actor_id,
            tenant_id,
            payment_id=payment_id,
            document_type=body.document_type,
            document_id=body.document_id,
            amount=body.amount,
            idempotency_key=body.idempotency_key,
        )
    )


@router.post("/tenants/{tenant_id}/payment-allocations/{allocation_id}/reverse")
def reverse_allocation_route(
    tenant_id: uuid.UUID,
    allocation_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _allocation_dict(_call(reverse_allocation, actor_id, tenant_id, allocation_id))


# --- Banking and reconciliation -------------------------------------------------------


@router.post("/tenants/{tenant_id}/bank-accounts", status_code=status.HTTP_201_CREATED)
def create_bank_account_route(
    tenant_id: uuid.UUID,
    body: CreateBankAccountRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bank_account_dict(
        _call(
            create_bank_account,
            actor_id,
            tenant_id,
            ledger_account_id=body.ledger_account_id,
            name=body.name,
            currency=body.currency,
            iban=body.iban,
        )
    )


@router.get("/tenants/{tenant_id}/bank-accounts")
def list_bank_accounts_route(
    tenant_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _bank_account_dict(v)
        for v in _call(list_bank_accounts, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/bank-accounts/{bank_account_id}")
def get_bank_account_route(
    tenant_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bank_account_dict(_call(get_bank_account, actor_id, tenant_id, bank_account_id))


@router.post(
    "/tenants/{tenant_id}/bank-accounts/{bank_account_id}/statements",
    status_code=status.HTTP_201_CREATED,
)
def import_bank_statement_route(
    tenant_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    body: ImportBankStatementRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bank_statement_dict(
        _call(
            import_bank_statement_csv,
            actor_id,
            tenant_id,
            bank_account_id=bank_account_id,
            csv_text=body.csv_text,
            period_start_date=body.period_start_date,
            period_end_date=body.period_end_date,
            reference=body.reference,
        )
    )


@router.get("/tenants/{tenant_id}/bank-statements/{bank_statement_id}/lines")
def list_bank_statement_lines_route(
    tenant_id: uuid.UUID,
    bank_statement_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _bank_statement_line_dict(v)
        for v in _call(
            list_bank_statement_lines,
            actor_id,
            tenant_id,
            bank_statement_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/tenants/{tenant_id}/bank-statement-lines/{line_id}/match-suggestions")
def suggest_matches_route(
    tenant_id: uuid.UUID,
    line_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [_match_candidate_dict(c) for c in _call(suggest_matches, actor_id, tenant_id, line_id)]


@router.post("/tenants/{tenant_id}/bank-statement-lines/{line_id}/match")
def confirm_match_route(
    tenant_id: uuid.UUID,
    line_id: uuid.UUID,
    body: ConfirmMatchRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bank_statement_line_dict(
        _call(
            confirm_match_to_document,
            actor_id,
            tenant_id,
            bank_statement_line_id=line_id,
            document_type=body.document_type,
            document_id=body.document_id,
        )
    )


@router.post("/tenants/{tenant_id}/bank-statement-lines/{line_id}/assign-account")
def assign_line_to_account_route(
    tenant_id: uuid.UUID,
    line_id: uuid.UUID,
    body: AssignLineToAccountRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _bank_statement_line_dict(
        _call(
            assign_line_to_account,
            actor_id,
            tenant_id,
            bank_statement_line_id=line_id,
            account_id=body.account_id,
        )
    )


__all__ = ["router"]
