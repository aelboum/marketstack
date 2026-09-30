"""Banking -- manual import and reconciliation (docs/ROADMAP.md Phase
15.5; `docs/ACCOUNTING-SCOPE.md` "Banking" + "Bank Integration Phasing"
step 1: "manual bank statement import (CSV, and MT940 if a target bank
commonly exports it), matched semi-automatically against open
invoices/expenses by amount/reference/date proximity, with a manual
confirm step. No live aggregation.").

**CSV only, this pass.** `import_bank_statement_csv()` is the one importer
this module ships. MT940 (a distinct SWIFT text format needing its own
parser) is deliberately deferred -- nothing here is CSV-specific past the
parsing boundary: `_parse_csv_lines()` is the only function that knows the
word "CSV," and it produces the identical `_ParsedLine` shape any future
`_parse_mt940_lines()` would; `_create_statement_in_session()` (the shared
import path both would call) never changes. `docs/ACCOUNTING-SCOPE.md`'s
own "Bank Integration Phasing" step 2 (a PSD2 AIS provider integration)
remains its own distinct, deliberately deferred future phase, Category D,
provider-abstracted from day one of *that* phase, never assumed or
half-built here.

**No HTTP route exposure this pass** -- unlike Phase 15.4's own explicit
"data model, service, API" scope line, Phase 15.5's own Scope line names
only "import service, matching algorithm, reconciliation workflow," never
an API. This mirrors Phase 24's own precedent (chart of accounts/periods/
journal shipped service-layer-only first) -- adding routes later is a
separate, explicitly-scoped, additive follow-up, never silently bundled in.

**Closes `Payment`'s own documented gap.** `product/accounting/payments.py
::Payment`'s own class docstring states plainly: "No cash-leg journal
entry is created for a payment this phase (Decision 8's own explicit
exclusion; no bank/cash GL account is designated yet)." Phase 15.5 is
what designates it -- `BankAccount.ledger_account_id` -- and this module
is what posts the missing cash-leg entry.

**`confirm_match_to_document()` is fully atomic**, in one transaction, the
same as `assign_line_to_account()`: it locks the target
`BankStatementLine` (`with_for_update=True`) *before* reading its status,
so a concurrent second call on the *same* line blocks until the first
commits or rolls back, then observes the now-`reconciled` status and is
rejected -- never creating a `Payment`. Rather than calling the public
`product/accounting/payments.py::create_payment()`/`create_allocation()`
(each its own separate transaction, which would reopen the very race the
row lock exists to close), it calls their internal, session-scoped
`_create_payment_in_session()`/`_create_allocation_in_session()` helpers
directly -- inside this same locked transaction -- exactly the way
`product/accounting/journal.py::_post_journal_entry_in_session()` is
already reused cross-module by `invoices.py`/`credit_notes.py`/this
module's own `assign_line_to_account()`. Because those two helpers skip
the public wrappers' own `require()` checks, this function re-asserts
`PAYMENT_RESOURCE.create`/`.allocate` itself immediately before calling
them, and replicates their own audit-log/event-publish calls afterward --
preserving the exact same authorization surface and observable side
effects as before, just atomic. A failure at any point (including the
allocation lock's own re-check of the document's remaining
`outstanding_amount`) rolls back the entire transaction -- the `Payment`
included -- so no orphan `Payment`/`PaymentAllocation` can ever survive a
failed reconciliation. `assign_line_to_account()` (no `Payment` involved)
was already fully atomic -- one transaction, one journal entry, one line
update.

**Duplicate detection**: `BankStatementLine.line_hash`
(`sha256(bank_account_id | transaction_date | amount | description)`) is
what makes re-importing an overlapping CSV file safe -- overlapping rows
recompute the identical hash and are skipped (never re-inserted, never
double-counted), backed by the database's own partial-free (always-
enforced) unique index as the final backstop against a concurrent-import
race, the same "advisory discipline + database backstop" shape this
module's own `_UNIQUE` patterns already use elsewhere in this package.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.accounting.errors import AccountingReferenceNotFoundError, AccountingValidationError
from product.accounting.journal import _post_journal_entry_in_session
from product.accounting.models import (
    ACCOUNT_TYPE_ASSET,
    ALLOCATION_DOCUMENT_TYPE_BILL,
    ALLOCATION_DOCUMENT_TYPE_INVOICE,
    BANK_LINE_STATUS_RECONCILED,
    BANK_LINE_STATUS_UNMATCHED,
    DOCUMENT_STATUS_POSTED,
    JOURNAL_ENTRY_STATUS_DRAFT,
    MAX_BANK_ACCOUNT_NAME_LENGTH,
    MAX_BANK_LINE_DESCRIPTION_LENGTH,
    MAX_BANK_STATEMENT_REFERENCE_LENGTH,
    MAX_COUNTERPARTY_REFERENCE_LENGTH,
    MAX_IBAN_LENGTH,
    PAYMENT_DIRECTION_INBOUND,
    PAYMENT_DIRECTION_OUTBOUND,
    ZERO,
    Account,
    BankAccount,
    BankStatement,
    BankStatementLine,
    Bill,
    Invoice,
    JournalEntry,
    JournalLine,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.payments import (
    ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE,
    ACCOUNTING_PAYMENT_ALLOCATED_EVENT_VERSION,
    ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE,
    ACCOUNTING_PAYMENT_CREATED_EVENT_VERSION,
    _create_allocation_in_session,
    _create_payment_in_session,
)
from product.accounting.permissions import BANKING_RESOURCE, PAYMENT_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE = "accounting.bank_statement.imported"
ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_VERSION = 1
ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE = "accounting.bank_line.reconciled"
ACCOUNTING_BANK_LINE_RECONCILED_EVENT_VERSION = 1

_DOCUMENT_MODEL_BY_TYPE: dict[str, type] = {
    ALLOCATION_DOCUMENT_TYPE_INVOICE: Invoice,
    ALLOCATION_DOCUMENT_TYPE_BILL: Bill,
}

#: How many ranked candidates `suggest_matches()` returns at most --
#: a bounded, cheap read, never an unbounded scan result.
_MAX_SUGGESTED_MATCHES = 5

#: Required CSV header, in this exact order (module docstring: CSV only,
#: this pass) -- a fixed, documented contract, never sniffed/inferred.
_CSV_COLUMNS = ("date", "amount", "description", "reference")


def _validate_currency(currency: str) -> str:
    normalized = currency.upper()
    Money(minor_units=0, currency=normalized)
    return normalized


def _validate_name(name: str) -> str:
    if not name or not name.strip():
        raise AccountingValidationError("name must not be empty.")
    if len(name) > MAX_BANK_ACCOUNT_NAME_LENGTH:
        raise AccountingValidationError(f"name exceeds {MAX_BANK_ACCOUNT_NAME_LENGTH} characters.")
    return name


def _validate_iban(iban: str | None) -> str | None:
    if iban is None:
        return None
    normalized = iban.replace(" ", "").upper()
    if not normalized or len(normalized) > MAX_IBAN_LENGTH:
        raise AccountingValidationError(f"iban must be at most {MAX_IBAN_LENGTH} characters.")
    return normalized


# --- Bank accounts (metadata only) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class BankAccountView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    ledger_account_id: uuid.UUID
    name: str
    iban: str | None
    currency: str
    created_at: datetime


def _bank_account_to_view(row: BankAccount) -> BankAccountView:
    return BankAccountView(
        id=row.id,
        tenant_id=row.tenant_id,
        ledger_account_id=row.ledger_account_id,
        name=row.name,
        iban=row.iban,
        currency=row.currency,
        created_at=row.created_at,
    )


def create_bank_account(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    ledger_account_id: uuid.UUID,
    name: str,
    currency: str,
    iban: str | None = None,
) -> BankAccountView:
    """`ledger_account_id` must name an existing, active, `asset`-typed
    `Account` -- a bank account posts as a real balance-sheet asset, never
    anything else."""
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="create")
    validated_name = _validate_name(name)
    validated_currency = _validate_currency(currency)
    validated_iban = _validate_iban(iban)

    with tenant_session_scope(tenant_id) as session:
        account = session.get(Account, ledger_account_id)
        if account is None or account.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", ledger_account_id)
        if account.account_type != ACCOUNT_TYPE_ASSET:
            raise AccountingValidationError(
                f"account {ledger_account_id} must be an '{ACCOUNT_TYPE_ASSET}' account."
            )
        if not account.is_active:
            raise AccountingValidationError(f"account {ledger_account_id} is not active.")

        bank_account_id = uuid.uuid4()
        try:
            session.add(
                BankAccount(
                    id=bank_account_id,
                    tenant_id=tenant_id,
                    ledger_account_id=ledger_account_id,
                    name=validated_name,
                    iban=validated_iban,
                    currency=validated_currency,
                )
            )
            session.flush()
        except IntegrityError as exc:
            raise AccountingValidationError(
                f"account {ledger_account_id} is already designated as a bank account."
            ) from exc
        row = session.get(BankAccount, bank_account_id)
        assert row is not None
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bank_account.created",
        resource_type="accounting.bank_account",
        resource_id=str(bank_account_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"ledger_account_id": str(ledger_account_id)},
    )
    return _bank_account_to_view(row)


def get_bank_account(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, bank_account_id: uuid.UUID
) -> BankAccountView:
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(BankAccount, bank_account_id)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bank_account", bank_account_id)
        session.expunge(row)
    return _bank_account_to_view(row)


def list_bank_accounts(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[BankAccountView]:
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(BankAccount)
                .where(BankAccount.tenant_id == tenant_id)
                .order_by(BankAccount.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_bank_account_to_view(row) for row in rows]


# --- Statement import (CSV only, module docstring) ----------------------------------


@dataclass(frozen=True, slots=True)
class _ParsedLine:
    transaction_date: date
    amount: Decimal
    description: str
    counterparty_reference: str | None


def _parse_csv_lines(csv_text: str) -> list[_ParsedLine]:
    """Fixed, documented column contract (module-level `_CSV_COLUMNS`):
    `date` (ISO `YYYY-MM-DD`), `amount` (signed decimal -- positive
    inflow, negative outflow), `description`, `reference` (optional,
    may be empty). No header sniffing, no locale-specific number/date
    formats -- a deterministic, minimal contract, matching this module's
    own "CSV only, this pass" scope."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or tuple(reader.fieldnames) != _CSV_COLUMNS:
        raise AccountingValidationError(
            f"CSV header must be exactly {','.join(_CSV_COLUMNS)!r}, "
            f"got: {','.join(reader.fieldnames or [])!r}."
        )
    parsed: list[_ParsedLine] = []
    for row_number, row in enumerate(reader, start=2):  # header is row 1
        raw_date = (row.get("date") or "").strip()
        raw_amount = (row.get("amount") or "").strip()
        description = (row.get("description") or "").strip()
        reference = (row.get("reference") or "").strip() or None
        if not raw_date or not raw_amount or not description:
            raise AccountingValidationError(
                f"CSV row {row_number}: date, amount, and description are required."
            )
        try:
            transaction_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise AccountingValidationError(
                f"CSV row {row_number}: date {raw_date!r} is not a valid YYYY-MM-DD date."
            ) from exc
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise AccountingValidationError(
                f"CSV row {row_number}: amount {raw_amount!r} is not a valid decimal."
            ) from exc
        if amount == ZERO:
            raise AccountingValidationError(f"CSV row {row_number}: amount must not be zero.")
        if len(description) > MAX_BANK_LINE_DESCRIPTION_LENGTH:
            raise AccountingValidationError(
                f"CSV row {row_number}: description exceeds "
                f"{MAX_BANK_LINE_DESCRIPTION_LENGTH} characters."
            )
        if reference is not None and len(reference) > MAX_COUNTERPARTY_REFERENCE_LENGTH:
            raise AccountingValidationError(
                f"CSV row {row_number}: reference exceeds "
                f"{MAX_COUNTERPARTY_REFERENCE_LENGTH} characters."
            )
        parsed.append(
            _ParsedLine(
                transaction_date=transaction_date,
                amount=amount,
                description=description,
                counterparty_reference=reference,
            )
        )
    if not parsed:
        raise AccountingValidationError("CSV file has no data rows.")
    return parsed


def _line_hash(bank_account_id: uuid.UUID, line: _ParsedLine) -> str:
    payload = (
        f"{bank_account_id}|{line.transaction_date.isoformat()}|{line.amount}|{line.description}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BankStatementLineView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    bank_statement_id: uuid.UUID
    bank_account_id: uuid.UUID
    line_no: int
    transaction_date: date
    amount: Decimal
    description: str
    counterparty_reference: str | None
    status: str
    matched_document_type: str | None
    matched_document_id: uuid.UUID | None
    matched_payment_id: uuid.UUID | None
    matched_account_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    reconciled_by_user_id: uuid.UUID | None
    reconciled_at: datetime | None
    created_at: datetime


def _line_to_view(row: BankStatementLine) -> BankStatementLineView:
    return BankStatementLineView(
        id=row.id,
        tenant_id=row.tenant_id,
        bank_statement_id=row.bank_statement_id,
        bank_account_id=row.bank_account_id,
        line_no=row.line_no,
        transaction_date=row.transaction_date.date(),
        amount=row.amount,
        description=row.description,
        counterparty_reference=row.counterparty_reference,
        status=row.status,
        matched_document_type=row.matched_document_type,
        matched_document_id=row.matched_document_id,
        matched_payment_id=row.matched_payment_id,
        matched_account_id=row.matched_account_id,
        journal_entry_id=row.journal_entry_id,
        reconciled_by_user_id=row.reconciled_by_user_id,
        reconciled_at=row.reconciled_at,
        created_at=row.created_at,
    )


@dataclass(frozen=True, slots=True)
class BankStatementView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    bank_account_id: uuid.UUID
    reference: str | None
    period_start_date: date
    period_end_date: date
    imported_by_user_id: uuid.UUID
    imported_at: datetime
    imported_line_count: int
    duplicate_line_count: int
    lines: tuple[BankStatementLineView, ...]


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def import_bank_statement_csv(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    bank_account_id: uuid.UUID,
    csv_text: str,
    period_start_date: date,
    period_end_date: date,
    reference: str | None = None,
) -> BankStatementView:
    """Parses `csv_text` (module docstring: fixed `date,amount,description,
    reference` header), creates one `BankStatement`, and inserts one
    `BankStatementLine` per parsed row -- skipping (never erroring on,
    never re-inserting) any row whose `line_hash` already exists for this
    `bank_account_id` (duplicate detection, module docstring). Returns the
    created statement together with both counts, so a caller can tell "12
    new, 3 already imported" apart from a silent full-duplicate no-op."""
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="create")
    if period_end_date < period_start_date:
        raise AccountingValidationError("period_end_date must not be before period_start_date.")
    validated_reference = None
    if reference:
        if len(reference) > MAX_BANK_STATEMENT_REFERENCE_LENGTH:
            raise AccountingValidationError(
                f"reference exceeds {MAX_BANK_STATEMENT_REFERENCE_LENGTH} characters."
            )
        validated_reference = reference
    parsed_lines = _parse_csv_lines(csv_text)

    with tenant_session_scope(tenant_id) as session:
        bank_account = session.get(BankAccount, bank_account_id)
        if bank_account is None or bank_account.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bank_account", bank_account_id)

        statement_id = uuid.uuid4()
        session.add(
            BankStatement(
                id=statement_id,
                tenant_id=tenant_id,
                bank_account_id=bank_account_id,
                reference=validated_reference,
                period_start_date=_date_to_utc_midnight(period_start_date),
                period_end_date=_date_to_utc_midnight(period_end_date),
                imported_by_user_id=actor_user_id,
            )
        )
        session.flush()

        existing_hashes = set(
            session.execute(
                select(BankStatementLine.line_hash).where(
                    BankStatementLine.tenant_id == tenant_id,
                    BankStatementLine.bank_account_id == bank_account_id,
                )
            )
            .scalars()
            .all()
        )
        imported_count = 0
        duplicate_count = 0
        for line_no, parsed in enumerate(parsed_lines, start=1):
            digest = _line_hash(bank_account_id, parsed)
            if digest in existing_hashes:
                duplicate_count += 1
                continue
            existing_hashes.add(digest)
            session.add(
                BankStatementLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    bank_statement_id=statement_id,
                    bank_account_id=bank_account_id,
                    line_no=line_no,
                    transaction_date=_date_to_utc_midnight(parsed.transaction_date),
                    amount=parsed.amount,
                    description=parsed.description,
                    counterparty_reference=parsed.counterparty_reference,
                    line_hash=digest,
                    status=BANK_LINE_STATUS_UNMATCHED,
                )
            )
            imported_count += 1
        session.flush()

        lines = (
            session.execute(
                select(BankStatementLine)
                .where(
                    BankStatementLine.tenant_id == tenant_id,
                    BankStatementLine.bank_statement_id == statement_id,
                )
                .order_by(BankStatementLine.line_no.asc())
            )
            .scalars()
            .all()
        )
        statement_row = session.get(BankStatement, statement_id)
        assert statement_row is not None
        view = BankStatementView(
            id=statement_row.id,
            tenant_id=statement_row.tenant_id,
            bank_account_id=statement_row.bank_account_id,
            reference=statement_row.reference,
            period_start_date=statement_row.period_start_date.date(),
            period_end_date=statement_row.period_end_date.date(),
            imported_by_user_id=statement_row.imported_by_user_id,
            imported_at=statement_row.imported_at,
            imported_line_count=imported_count,
            duplicate_line_count=duplicate_count,
            lines=tuple(_line_to_view(line) for line in lines),
        )

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bank_statement.imported",
        resource_type="accounting.bank_statement",
        resource_id=str(statement_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "bank_account_id": str(bank_account_id),
            "imported_line_count": imported_count,
            "duplicate_line_count": duplicate_count,
        },
    )
    publish(
        Event(
            type=ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE,
            version=ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "bank_statement_id": str(statement_id),
                "bank_account_id": str(bank_account_id),
                "imported_line_count": imported_count,
            },
        )
    )
    return view


def _get_owned_line(
    session, tenant_id: uuid.UUID, bank_statement_line_id: uuid.UUID
) -> BankStatementLine:
    row = session.get(BankStatementLine, bank_statement_line_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("bank_statement_line", bank_statement_line_id)
    return row


def list_bank_statement_lines(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    bank_statement_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[BankStatementLineView]:
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        statement = session.get(BankStatement, bank_statement_id)
        if statement is None or statement.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bank_statement", bank_statement_id)
        conditions = [
            BankStatementLine.tenant_id == tenant_id,
            BankStatementLine.bank_statement_id == bank_statement_id,
        ]
        if status is not None:
            conditions.append(BankStatementLine.status == status)
        rows = (
            session.execute(
                select(BankStatementLine)
                .where(*conditions)
                .order_by(BankStatementLine.line_no.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_line_to_view(row) for row in rows]


# --- Matching suggestion (read-only, never persisted -- module docstring) ----------


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    document_type: str
    document_id: uuid.UUID
    outstanding_amount: Decimal
    contact_id: uuid.UUID
    reference_date: date


def suggest_matches(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, bank_statement_line_id: uuid.UUID
) -> list[MatchCandidate]:
    """Ranks open (`posted`, `outstanding_amount > 0`) `Invoice`s (for an
    inflow line, `amount > 0`) or `Bill`s (for an outflow line) by amount
    proximity to `abs(line.amount)` first, then by date proximity to the
    line's own `transaction_date` -- "matched... by amount/reference/date
    proximity" (`docs/ACCOUNTING-SCOPE.md` "Bank Integration Phasing" step
    1). Read-only: never writes anything, never called by
    `confirm_match_to_document()` (module docstring's own "stateless
    suggestion" design) -- a caller is free to ignore every candidate and
    match a different document entirely."""
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        line = _get_owned_line(session, tenant_id, bank_statement_line_id)
        if line.status != BANK_LINE_STATUS_UNMATCHED:
            raise AccountingValidationError(
                f"bank statement line {bank_statement_line_id} is already "
                f"{line.status!r}, not unmatched."
            )
        target_amount = abs(line.amount)
        is_inflow = line.amount > ZERO
        model = Invoice if is_inflow else Bill
        rows = (
            session.execute(
                select(model).where(
                    model.tenant_id == tenant_id,
                    model.status == DOCUMENT_STATUS_POSTED,
                    model.outstanding_amount > ZERO,
                )
            )
            .scalars()
            .all()
        )
        line_date = line.transaction_date.date()

        def _sort_key(row: object) -> tuple[Decimal, int]:
            amount_delta = abs(row.outstanding_amount - target_amount)  # type: ignore[attr-defined]
            reference_date = (
                row.due_date.date() if is_inflow else row.due_date.date()  # type: ignore[attr-defined]
            )
            date_delta = abs((reference_date - line_date).days)
            return (amount_delta, date_delta)

        ranked = sorted(rows, key=_sort_key)[:_MAX_SUGGESTED_MATCHES]
        document_type = (
            ALLOCATION_DOCUMENT_TYPE_INVOICE if is_inflow else ALLOCATION_DOCUMENT_TYPE_BILL
        )
        candidates = [
            MatchCandidate(
                document_type=document_type,
                document_id=row.id,
                outstanding_amount=row.outstanding_amount,
                contact_id=row.contact_id,
                reference_date=row.due_date.date(),
            )
            for row in ranked
        ]
    return candidates


# --- Reconciliation (mutating -- module docstring's own atomicity notes) ----------


def confirm_match_to_document(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    bank_statement_line_id: uuid.UUID,
    document_type: str,
    document_id: uuid.UUID,
) -> BankStatementLineView:
    """Confirms an unmatched line against a specific, caller-chosen
    invoice/bill (module docstring: the suggestion is advisory only, never
    required). Requires an exact amount match --
    `abs(line.amount) == document.outstanding_amount` -- a partial-payment
    reconciliation is deliberately not built this pass (not named by
    Phase 15.5's own Tests/Acceptance-criteria text; `create_allocation()`
    itself already supports a partial amount, so a future phase can relax
    this to `<=` without any schema change).

    Fully atomic (module docstring) -- the line is locked
    (`with_for_update=True`) before its status is even read, so a
    concurrent second confirmation of the *same* line blocks until this
    one finishes, then correctly observes `reconciled` and is rejected
    before ever creating a `Payment`."""
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="reconcile")
    if document_type not in _DOCUMENT_MODEL_BY_TYPE:
        raise AccountingValidationError(
            f"document_type must be one of {tuple(_DOCUMENT_MODEL_BY_TYPE)}, got: "
            f"{document_type!r}."
        )

    with tenant_session_scope(tenant_id) as session:
        line = session.get(BankStatementLine, bank_statement_line_id, with_for_update=True)
        if line is None or line.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bank_statement_line", bank_statement_line_id)
        if line.status != BANK_LINE_STATUS_UNMATCHED:
            raise AccountingValidationError(
                f"bank statement line {bank_statement_line_id} is already "
                f"{line.status!r}, not unmatched."
            )
        bank_account = session.get(BankAccount, line.bank_account_id)
        assert bank_account is not None  # FK-enforced

        model = _DOCUMENT_MODEL_BY_TYPE[document_type]
        document = session.get(model, document_id)
        if document is None or document.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError(document_type, document_id)
        if document.status != DOCUMENT_STATUS_POSTED:
            raise AccountingValidationError(
                f"{document_type} {document_id} cannot be reconciled while "
                f"status={document.status!r} (only 'posted' documents can be)."
            )
        is_inflow = line.amount > ZERO
        expected_type = (
            ALLOCATION_DOCUMENT_TYPE_INVOICE if is_inflow else ALLOCATION_DOCUMENT_TYPE_BILL
        )
        if document_type != expected_type:
            raise AccountingValidationError(
                f"an inflow line may only match an {ALLOCATION_DOCUMENT_TYPE_INVOICE}, "
                f"an outflow line only a {ALLOCATION_DOCUMENT_TYPE_BILL} "
                f"(got document_type={document_type!r})."
            )
        line_amount = abs(line.amount)
        if line_amount != document.outstanding_amount:
            raise AccountingValidationError(
                f"{document_type} {document_id}'s outstanding_amount "
                f"({document.outstanding_amount}) does not exactly match this line's own "
                f"amount ({line_amount})."
            )
        contact_id = document.contact_id
        document_currency = document.currency
        counterparty_account_id = (
            document.receivable_account_id if is_inflow else document.payable_account_id
        )
        ledger_account_id = bank_account.ledger_account_id
        line_transaction_date = line.transaction_date

        # Reuses the existing payment/allocation business logic (module
        # docstring) via its own internal, session-scoped helpers -- inside
        # this same locked transaction, never a separate one -- so a
        # failure anywhere below (including the allocation lock's own
        # re-check of the document's remaining outstanding_amount) rolls
        # back the Payment too. The public create_payment()/
        # create_allocation() wrappers are deliberately not called: each is
        # its own separate transaction, which would reopen the very race
        # this lock exists to close. Their own require() checks are
        # skipped by calling the internal helpers directly, so both are
        # re-asserted explicitly here.
        direction = PAYMENT_DIRECTION_INBOUND if is_inflow else PAYMENT_DIRECTION_OUTBOUND
        require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="create")
        payment_result = _create_payment_in_session(
            session,
            tenant_id,
            actor_user_id,
            contact_id=contact_id,
            direction=direction,
            amount=line_amount,
            currency=document_currency,
            reference=f"Bank reconciliation: statement line {bank_statement_line_id}",
        )
        payment_id = uuid.UUID(str(payment_result["payment_id"]))

        require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="allocate")
        allocation_result = _create_allocation_in_session(
            session,
            tenant_id,
            actor_user_id,
            payment_id=payment_id,
            document_type=document_type,
            document_id=document_id,
            amount=line_amount,
        )
        allocation_id = uuid.UUID(str(allocation_result["allocation_id"]))

        journal_entry_id = uuid.uuid4()
        session.add(
            JournalEntry(
                id=journal_entry_id,
                tenant_id=tenant_id,
                entry_date=line_transaction_date,
                currency=document_currency,
                description=f"Bank reconciliation: {document_type} {document_id}",
                status=JOURNAL_ENTRY_STATUS_DRAFT,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()
        if is_inflow:
            # Cash received: Dr bank account, Cr the invoice's own
            # receivable account (reducing what is owed).
            debit_account_id, credit_account_id = ledger_account_id, counterparty_account_id
        else:
            # Cash paid out: Dr the bill's own payable account (reducing
            # what is owed), Cr bank account.
            debit_account_id, credit_account_id = counterparty_account_id, ledger_account_id
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=debit_account_id,
                debit_amount=line_amount,
                credit_amount=ZERO,
            )
        )
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=credit_account_id,
                debit_amount=ZERO,
                credit_amount=line_amount,
            )
        )
        session.flush()
        _post_journal_entry_in_session(session, tenant_id, journal_entry_id, actor_user_id)

        line.status = BANK_LINE_STATUS_RECONCILED
        line.matched_document_type = document_type
        line.matched_document_id = document_id
        line.matched_payment_id = payment_id
        line.journal_entry_id = journal_entry_id
        line.reconciled_by_user_id = actor_user_id
        line.reconciled_at = datetime.now(UTC)
        session.flush()
        session.refresh(line)
        session.expunge(line)

    # Replicates create_payment()'s/create_allocation()'s own audit/event
    # side effects (skipped above by calling their internal helpers
    # directly) so a payment/allocation created via bank reconciliation
    # remains observable exactly like one created through the public API.
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.payment.created",
        resource_type="accounting.payment",
        resource_id=str(payment_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"contact_id": str(contact_id), "direction": direction},
    )
    publish(
        Event(
            type=ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE,
            version=ACCOUNTING_PAYMENT_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"payment_id": str(payment_id), "contact_id": str(contact_id)},
        )
    )
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.payment_allocation.created",
        resource_type="accounting.payment_allocation",
        resource_id=str(allocation_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "payment_id": str(payment_id),
            "document_type": document_type,
            "document_id": str(document_id),
        },
    )
    publish(
        Event(
            type=ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE,
            version=ACCOUNTING_PAYMENT_ALLOCATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "payment_id": str(payment_id),
                "document_type": document_type,
                "document_id": str(document_id),
                "allocation_id": str(allocation_id),
            },
        )
    )
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bank_line.reconciled",
        resource_type="accounting.bank_statement_line",
        resource_id=str(bank_statement_line_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "matched_document_type": document_type,
            "matched_document_id": str(document_id),
            "payment_id": str(payment_id),
        },
    )
    publish(
        Event(
            type=ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE,
            version=ACCOUNTING_BANK_LINE_RECONCILED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "bank_statement_line_id": str(bank_statement_line_id),
                "matched_document_type": document_type,
                "matched_document_id": str(document_id),
            },
        )
    )
    return _line_to_view(line)


def assign_line_to_account(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    bank_statement_line_id: uuid.UUID,
    account_id: uuid.UUID,
) -> BankStatementLineView:
    """For a line with no matching invoice/bill (a bank fee, interest, an
    expense never entered as a `Bill`) -- posts a direct `JournalEntry`
    between the bank account's own ledger account and `account_id`, fully
    atomically (module docstring: unlike `confirm_match_to_document()`,
    no `Payment` is involved, so this is one single transaction)."""
    require(actor_user_id, tenant_id, resource=BANKING_RESOURCE, action="reconcile")

    with tenant_session_scope(tenant_id) as session:
        row = session.get(BankStatementLine, bank_statement_line_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("bank_statement_line", bank_statement_line_id)
        if row.status != BANK_LINE_STATUS_UNMATCHED:
            raise AccountingValidationError(
                f"bank statement line {bank_statement_line_id} is already "
                f"{row.status!r}, not unmatched."
            )
        bank_account = session.get(BankAccount, row.bank_account_id)
        assert bank_account is not None  # FK-enforced

        target_account = session.get(Account, account_id)
        if target_account is None or target_account.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", account_id)
        if not target_account.is_active:
            raise AccountingValidationError(f"account {account_id} is not active.")

        line_amount = abs(row.amount)
        is_inflow = row.amount > ZERO
        journal_entry_id = uuid.uuid4()
        session.add(
            JournalEntry(
                id=journal_entry_id,
                tenant_id=tenant_id,
                entry_date=row.transaction_date,
                currency=bank_account.currency,
                description=f"Bank line assigned: {row.description}"[:500],
                status=JOURNAL_ENTRY_STATUS_DRAFT,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()
        if is_inflow:
            debit_account_id, credit_account_id = bank_account.ledger_account_id, account_id
        else:
            debit_account_id, credit_account_id = account_id, bank_account.ledger_account_id
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=debit_account_id,
                debit_amount=line_amount,
                credit_amount=ZERO,
            )
        )
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=journal_entry_id,
                account_id=credit_account_id,
                debit_amount=ZERO,
                credit_amount=line_amount,
            )
        )
        session.flush()
        _post_journal_entry_in_session(session, tenant_id, journal_entry_id, actor_user_id)

        row.status = BANK_LINE_STATUS_RECONCILED
        row.matched_account_id = account_id
        row.journal_entry_id = journal_entry_id
        row.reconciled_by_user_id = actor_user_id
        row.reconciled_at = datetime.now(UTC)
        session.flush()
        session.refresh(row)
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.bank_line.reconciled",
        resource_type="accounting.bank_statement_line",
        resource_id=str(bank_statement_line_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"matched_account_id": str(account_id)},
    )
    publish(
        Event(
            type=ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE,
            version=ACCOUNTING_BANK_LINE_RECONCILED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={
                "bank_statement_line_id": str(bank_statement_line_id),
                "matched_account_id": str(account_id),
            },
        )
    )
    return _line_to_view(row)


__all__ = [
    "ACCOUNTING_BANK_LINE_RECONCILED_EVENT_TYPE",
    "ACCOUNTING_BANK_STATEMENT_IMPORTED_EVENT_TYPE",
    "BankAccountView",
    "BankStatementLineView",
    "BankStatementView",
    "MatchCandidate",
    "assign_line_to_account",
    "confirm_match_to_document",
    "create_bank_account",
    "get_bank_account",
    "import_bank_statement_csv",
    "list_bank_accounts",
    "list_bank_statement_lines",
    "suggest_matches",
]
