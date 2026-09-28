"""Journal entries -- the double-entry ledger itself (docs/ROADMAP.md
Phase 24, ADR-0014 Decisions 2-5, and the journal-only slice of 9-11).

**Lifecycle** (Decision 3): `draft -> posted`, `draft -> voided`,
`posted -> reversed`. `create_journal_entry()`/`update_journal_entry()`
do **not** enforce `sum(debits) == sum(credits)` -- a `draft` entry "has
no financial effect" (Decision 3) and "may be edited... freely," so this
module lets a caller build one up incrementally without forcing balance
until the moment that matters. `post_journal_entry()` is where the
invariant is actually enforced, inside the same transaction as the
status flip, before any commit (Decision 4's own disclosed exception:
the one accounting invariant in this module that is service-layer-only,
not also a database `CHECK` -- Postgres has no cross-row `CHECK`).

**Period resolution** (Decision 5): `post_journal_entry()`/
`reverse_journal_entry()` look up the period covering the entry's own
date themselves -- a caller never supplies `period_id` directly.
`AccountingPeriodNotFoundError` if no period at all covers that date;
`AccountingPeriodClosedError` if one does but is `closed`. Both take
`infra.db.acquire_tenant_advisory_lock(session, tenant_id,
f"accounting.period.{period_id}")` on the *found* period before
re-reading its status and proceeding -- the period's own date boundaries
never change once created (`product/accounting/periods.py`'s own "no
`update_period()`" discipline), so looking the period up unlocked and
then locking-and-re-checking its (the only mutable field) `status` is
safe, exactly mirroring `core.usage.service._consume_quota_in_session()`'s
own lock-before-read pattern.

**Idempotency** (Decision 11, journal slice only): `post_journal_entry()`/
`reverse_journal_entry()` each accept an optional `idempotency_key`; when
supplied, the entire mutation runs through `core.idempotency
.run_idempotent()` -- the fully atomic, single-transaction primitive,
following `core.usage.service.consume_quota_idempotent()`'s exact model
(the business function receives the *same* session the reservation was
inserted through). No API layer exists yet this phase to read an
`Idempotency-Key` header (`docs/ROADMAP.md` Phase 24's own "no
cross-domain integration required" scope, Step 18) -- a future API layer
reads it via `api.dependencies.get_idempotency_key()` exactly like every
other endpoint, per Decision 11's own stated plan; nothing here invents a
second mechanism.

**Events published, journal-level only** (Decision 10's own journal-event
slice): `ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE`/`..._REVERSED_EVENT_TYPE`.
Deliberately **not** published this phase: `accounting.period.closed`/
`.reopened` (Decision 10's broader list names `accounting.period.closed`,
but groups it alongside the invoice/bill/payment events that are Phase
25's own scope, not Phase 24's -- this phase's own event boundary is
"journal-level only," so period-lifecycle events are left for whoever
scopes their own real consumer, rather than publishing one speculatively
now) and every `accounting.invoice.*`/`.bill.*`/`.payment.*` event
(Phase 25).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import run_idempotent
from infra.db import acquire_tenant_advisory_lock, delete, select, tenant_session_scope

from product.accounting.errors import (
    AccountingPeriodClosedError,
    AccountingPeriodNotFoundError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.models import (
    JOURNAL_ENTRY_STATUS_DRAFT,
    JOURNAL_ENTRY_STATUS_POSTED,
    JOURNAL_ENTRY_STATUS_REVERSED,
    JOURNAL_ENTRY_STATUS_VOIDED,
    MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH,
    PERIOD_STATUS_CLOSED,
    ZERO,
    Account,
    JournalEntry,
    JournalLine,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.periods import find_period_for_date
from product.accounting.permissions import JOURNAL_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE = "accounting.journal.posted"
ACCOUNTING_JOURNAL_POSTED_EVENT_VERSION = 1
ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE = "accounting.journal.reversed"
ACCOUNTING_JOURNAL_REVERSED_EVENT_VERSION = 1

_MIN_LINES = 2  # A balanced entry mathematically needs at least two lines
# (module docstring's own "exactly one side per line" invariant makes a
# single-line entry unable to balance except at zero, which is itself
# disallowed).


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _validate_currency(currency: str) -> str:
    """Reuses `product.foundation.values.Money`'s own currency-shape
    validation (constructed only to trigger its `__post_init__` check,
    then discarded -- this module never uses `Money`'s own integer-minor-
    units representation, per ADR-0014 Decision 4). `InvalidCurrencyCodeError`
    propagates unchanged on a malformed code, mirroring
    `product/crm/contacts.py`'s own documented "propagates unchanged"
    precedent for `InvalidPhoneNumberError`. Uppercased *before*
    validation, not after -- `Money.__post_init__()` itself requires
    uppercase (`Money.from_decimal()`'s own "currency.upper()" convention
    normalizes first for the identical reason), so a lowercase-but-
    otherwise-valid code like `"eur"` must be normalized before Money
    ever sees it, not rejected by it."""
    normalized = currency.upper()
    Money(minor_units=0, currency=normalized)
    return normalized


def _validate_description(description: str) -> str:
    if len(description) > MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH:
        raise AccountingValidationError(
            f"description must be at most {MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH} characters."
        )
    return description


@dataclass(frozen=True, slots=True)
class JournalLineInput:
    account_id: uuid.UUID
    debit_amount: Decimal = ZERO
    credit_amount: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class JournalLineView:
    id: uuid.UUID
    account_id: uuid.UUID
    debit_amount: Decimal
    credit_amount: Decimal


@dataclass(frozen=True, slots=True)
class JournalEntryView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    entry_date: date
    currency: str
    description: str | None
    status: str
    period_id: uuid.UUID | None
    reverses_entry_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    posted_by_user_id: uuid.UUID | None
    posted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[JournalLineView, ...]


def _to_view(row: JournalEntry, lines: list[JournalLine]) -> JournalEntryView:
    return JournalEntryView(
        id=row.id,
        tenant_id=row.tenant_id,
        entry_date=row.entry_date.date(),
        currency=row.currency,
        description=row.description,
        status=row.status,
        period_id=row.period_id,
        reverses_entry_id=row.reverses_entry_id,
        created_by_user_id=row.created_by_user_id,
        posted_by_user_id=row.posted_by_user_id,
        posted_at=row.posted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        lines=tuple(
            JournalLineView(
                id=line.id,
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
            )
            for line in lines
        ),
    )


def _validate_lines(
    session, tenant_id: uuid.UUID, lines: list[JournalLineInput]
) -> list[JournalLineInput]:
    """Validates each line's own shape (exactly one side positive, a
    real active account in this tenant) -- never the whole entry's
    balance, which `post_journal_entry()` alone enforces (module
    docstring)."""
    if len(lines) < _MIN_LINES:
        raise AccountingValidationError(
            f"a journal entry needs at least {_MIN_LINES} lines to balance."
        )
    validated: list[JournalLineInput] = []
    for line in lines:
        debit = line.debit_amount if line.debit_amount is not None else ZERO
        credit = line.credit_amount if line.credit_amount is not None else ZERO
        one_side_positive = (debit > ZERO and credit == ZERO) or (credit > ZERO and debit == ZERO)
        if not one_side_positive:
            raise AccountingValidationError(
                "each line must have exactly one of debit_amount/credit_amount strictly "
                "positive and the other exactly zero."
            )
        account = session.get(Account, line.account_id)
        if account is None or account.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("account", line.account_id)
        if not account.is_active:
            raise AccountingValidationError(f"account {line.account_id} is not active.")
        validated.append(
            JournalLineInput(account_id=line.account_id, debit_amount=debit, credit_amount=credit)
        )
    return validated


def _load_view(tenant_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntryView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(JournalEntry, entry_id)
        assert row is not None
        lines = (
            session.execute(
                select(JournalLine)
                .where(JournalLine.tenant_id == tenant_id, JournalLine.journal_entry_id == entry_id)
                .order_by(JournalLine.created_at.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
        session.expunge(row)
        for line in lines:
            session.expunge(line)
    return view


def create_journal_entry(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    entry_date: date,
    currency: str,
    lines: list[JournalLineInput],
    description: str | None = None,
) -> JournalEntryView:
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="create")
    validated_currency = _validate_currency(currency)
    validated_description = _validate_description(description) if description else None

    entry_id = uuid.uuid4()
    with tenant_session_scope(tenant_id) as session:
        validated_lines = _validate_lines(session, tenant_id, lines)
        session.add(
            JournalEntry(
                id=entry_id,
                tenant_id=tenant_id,
                entry_date=_date_to_utc_midnight(entry_date),
                currency=validated_currency,
                description=validated_description,
                status=JOURNAL_ENTRY_STATUS_DRAFT,
                created_by_user_id=actor_user_id,
            )
        )
        session.flush()
        for line in validated_lines:
            session.add(
                JournalLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    journal_entry_id=entry_id,
                    account_id=line.account_id,
                    debit_amount=line.debit_amount,
                    credit_amount=line.credit_amount,
                )
            )
        session.flush()

    view = _load_view(tenant_id, entry_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.journal_entry.created",
        resource_type="accounting.journal_entry",
        resource_id=str(entry_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"line_count": len(view.lines)},
    )
    return view


def _get_owned_row(session, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
    row = session.get(JournalEntry, entry_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("journal_entry", entry_id)
    return row


def get_journal_entry(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, entry_id: uuid.UUID
) -> JournalEntryView:
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, entry_id)
        lines = (
            session.execute(
                select(JournalLine)
                .where(JournalLine.tenant_id == tenant_id, JournalLine.journal_entry_id == entry_id)
                .order_by(JournalLine.created_at.asc())
            )
            .scalars()
            .all()
        )
        view = _to_view(row, list(lines))
    return view


def list_journal_entries(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[JournalEntryView]:
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(JournalEntry)
                .where(JournalEntry.tenant_id == tenant_id)
                .order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
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
                    select(JournalLine)
                    .where(
                        JournalLine.tenant_id == tenant_id,
                        JournalLine.journal_entry_id == row.id,
                    )
                    .order_by(JournalLine.created_at.asc())
                )
                .scalars()
                .all()
            )
            views.append(_to_view(row, list(lines)))
    return views


def update_journal_entry(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    description: str | None = ...,  # type: ignore[assignment] -- sentinel: omitted vs. explicit None
    lines: list[JournalLineInput] | None = None,
) -> JournalEntryView:
    """Only while `status == draft` (Decision 3: "may be edited... freely").
    `currency`/`entry_date` are not editable this phase -- changing either
    after lines have been added against a specific currency assumption
    would reopen the multi-currency question this phase deliberately does
    not answer (Decision 4); create a new draft instead."""
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, entry_id)
        if row.status != JOURNAL_ENTRY_STATUS_DRAFT:
            raise AccountingValidationError(
                f"journal entry {entry_id} cannot be edited while status={row.status!r} "
                "(only 'draft' entries can be)."
            )
        if description is not ...:
            row.description = _validate_description(description) if description else None
        if lines is not None:
            validated_lines = _validate_lines(session, tenant_id, lines)
            session.execute(
                delete(JournalLine).where(
                    JournalLine.tenant_id == tenant_id, JournalLine.journal_entry_id == entry_id
                )
            )
            session.flush()
            for line in validated_lines:
                session.add(
                    JournalLine(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        journal_entry_id=entry_id,
                        account_id=line.account_id,
                        debit_amount=line.debit_amount,
                        credit_amount=line.credit_amount,
                    )
                )
        session.flush()

    view = _load_view(tenant_id, entry_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.journal_entry.updated",
        resource_type="accounting.journal_entry",
        resource_id=str(entry_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"line_count": len(view.lines)},
    )
    return view


def void_journal_entry(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, entry_id: uuid.UUID
) -> JournalEntryView:
    """`draft -> voided` (Decision 3) -- discarding something that was
    never posted, not a correction. Row-locked (`with_for_update=True`)
    to close the same double-action race `staff_cancel_appointment()`'s
    own precedent closes."""
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="void")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(JournalEntry, entry_id, with_for_update=True)
        if row is None or row.tenant_id != tenant_id:
            raise AccountingReferenceNotFoundError("journal_entry", entry_id)
        if row.status != JOURNAL_ENTRY_STATUS_DRAFT:
            raise AccountingValidationError(
                f"journal entry {entry_id} cannot be voided while status={row.status!r} "
                "(only 'draft' entries can be)."
            )
        row.status = JOURNAL_ENTRY_STATUS_VOIDED
        session.flush()

    view = _load_view(tenant_id, entry_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.journal_entry.voided",
        resource_type="accounting.journal_entry",
        resource_id=str(entry_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return view


def _post_journal_entry_in_session(
    session, tenant_id: uuid.UUID, entry_id: uuid.UUID, actor_user_id: uuid.UUID
) -> dict[str, object]:
    row = session.get(JournalEntry, entry_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("journal_entry", entry_id)
    if row.status != JOURNAL_ENTRY_STATUS_DRAFT:
        raise AccountingValidationError(
            f"journal entry {entry_id} cannot be posted while status={row.status!r} "
            "(only 'draft' entries can be)."
        )

    lines = (
        session.execute(
            select(JournalLine).where(
                JournalLine.tenant_id == tenant_id, JournalLine.journal_entry_id == entry_id
            )
        )
        .scalars()
        .all()
    )
    if len(lines) < _MIN_LINES:
        raise AccountingValidationError(
            f"journal entry {entry_id} needs at least {_MIN_LINES} lines to post."
        )
    total_debits = sum((line.debit_amount for line in lines), ZERO)
    total_credits = sum((line.credit_amount for line in lines), ZERO)
    if total_debits != total_credits:
        raise AccountingValidationError(
            f"journal entry {entry_id} is not balanced: "
            f"total debits {total_debits} != total credits {total_credits}."
        )

    entry_date = row.entry_date.date()
    period = find_period_for_date(session, tenant_id, entry_date)
    if period is None:
        raise AccountingPeriodNotFoundError(tenant_id, entry_date)
    acquire_tenant_advisory_lock(session, tenant_id, f"accounting.period.{period.id}")
    session.refresh(period)
    if period.status == PERIOD_STATUS_CLOSED:
        raise AccountingPeriodClosedError(tenant_id, period.id)

    row.status = JOURNAL_ENTRY_STATUS_POSTED
    row.period_id = period.id
    row.posted_by_user_id = actor_user_id
    row.posted_at = datetime.now(UTC)
    session.flush()
    return {"entry_id": str(entry_id), "period_id": str(period.id)}


def post_journal_entry(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> JournalEntryView:
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="post")

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _post_journal_entry_in_session(session, tenant_id, entry_id, actor_user_id)
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _post_journal_entry_in_session(session, tenant_id, entry_id, actor_user_id)

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.journal.post",
            idempotency_key,
            fingerprint_payload={"entry_id": str(entry_id)},
            business_fn=_business,
        )

    view = _load_view(tenant_id, entry_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.journal_entry.posted",
            resource_type="accounting.journal_entry",
            resource_id=str(entry_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"period_id": str(result["period_id"])},
        )
        publish(
            Event(
                type=ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE,
                version=ACCOUNTING_JOURNAL_POSTED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"journal_entry_id": str(entry_id), "period_id": str(result["period_id"])},
            )
        )
    return view


def _reverse_journal_entry_in_session(
    session,
    tenant_id: uuid.UUID,
    original_entry_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reversal_entry_date: date,
    description: str | None,
) -> dict[str, object]:
    original = session.get(JournalEntry, original_entry_id, with_for_update=True)
    if original is None or original.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("journal_entry", original_entry_id)
    if original.status != JOURNAL_ENTRY_STATUS_POSTED:
        raise AccountingValidationError(
            f"journal entry {original_entry_id} cannot be reversed while "
            f"status={original.status!r} (only 'posted' entries can be)."
        )

    original_lines = (
        session.execute(
            select(JournalLine).where(
                JournalLine.tenant_id == tenant_id,
                JournalLine.journal_entry_id == original_entry_id,
            )
        )
        .scalars()
        .all()
    )

    period = find_period_for_date(session, tenant_id, reversal_entry_date)
    if period is None:
        raise AccountingPeriodNotFoundError(tenant_id, reversal_entry_date)
    acquire_tenant_advisory_lock(session, tenant_id, f"accounting.period.{period.id}")
    session.refresh(period)
    if period.status == PERIOD_STATUS_CLOSED:
        raise AccountingPeriodClosedError(tenant_id, period.id)

    reversal_id = uuid.uuid4()
    resolved_description = (
        _validate_description(description)
        if description
        else f"Reversal of journal entry {original_entry_id}"
    )
    session.add(
        JournalEntry(
            id=reversal_id,
            tenant_id=tenant_id,
            entry_date=_date_to_utc_midnight(reversal_entry_date),
            currency=original.currency,
            description=resolved_description,
            status=JOURNAL_ENTRY_STATUS_POSTED,
            period_id=period.id,
            reverses_entry_id=original_entry_id,
            created_by_user_id=actor_user_id,
            posted_by_user_id=actor_user_id,
            posted_at=datetime.now(UTC),
        )
    )
    session.flush()
    for line in original_lines:
        # Exact debit/credit mirror -- every debit becomes a credit and
        # vice versa, same accounts, same amounts (ADR-0014 Decision 3).
        # Still balanced: the original's own total_debits == total_credits
        # (it was posted), so the mirrored totals are equal too.
        session.add(
            JournalLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                journal_entry_id=reversal_id,
                account_id=line.account_id,
                debit_amount=line.credit_amount,
                credit_amount=line.debit_amount,
            )
        )
    original.status = JOURNAL_ENTRY_STATUS_REVERSED
    session.flush()
    return {"reversal_entry_id": str(reversal_id), "period_id": str(period.id)}


def reverse_journal_entry(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    reversal_entry_date: date | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> JournalEntryView:
    """Returns the **new** reversing entry's own view (not the original's
    -- callers wanting the original's now-`reversed` status call
    `get_journal_entry(entry_id)` separately). `reversal_entry_date`
    defaults to today (UTC) if omitted -- a disclosed, undecided-by-ADR-
    0014 default, not a hidden one: the ADR requires a reversal to
    "respect accounting-period locking" but never specifies which date the
    correction itself is posted under, so this module resolves it to
    "today" rather than silently reusing the original's own (possibly
    now-closed) period."""
    require(actor_user_id, tenant_id, resource=JOURNAL_RESOURCE, action="reverse")
    resolved_date = (
        reversal_entry_date if reversal_entry_date is not None else datetime.now(UTC).date()
    )

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _reverse_journal_entry_in_session(
                session, tenant_id, entry_id, actor_user_id, resolved_date, description
            )
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _reverse_journal_entry_in_session(
                session, tenant_id, entry_id, actor_user_id, resolved_date, description
            )

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.journal.reverse",
            idempotency_key,
            fingerprint_payload={
                "entry_id": str(entry_id),
                "reversal_entry_date": resolved_date.isoformat(),
            },
            business_fn=_business,
        )

    reversal_entry_id = uuid.UUID(str(result["reversal_entry_id"]))
    view = _load_view(tenant_id, reversal_entry_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.journal_entry.reversed",
            resource_type="accounting.journal_entry",
            resource_id=str(entry_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={
                "reversal_entry_id": str(reversal_entry_id),
                "period_id": str(result["period_id"]),
            },
        )
        publish(
            Event(
                type=ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE,
                version=ACCOUNTING_JOURNAL_REVERSED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={
                    "journal_entry_id": str(entry_id),
                    "reversal_entry_id": str(reversal_entry_id),
                    "period_id": str(result["period_id"]),
                },
            )
        )
    return view


__all__ = [
    "ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE",
    "ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE",
    "JournalEntryView",
    "JournalLineInput",
    "JournalLineView",
    "create_journal_entry",
    "get_journal_entry",
    "list_journal_entries",
    "post_journal_entry",
    "reverse_journal_entry",
    "update_journal_entry",
    "void_journal_entry",
]
