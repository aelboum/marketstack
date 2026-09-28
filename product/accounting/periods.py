"""Accounting-period management (docs/ROADMAP.md Phase 24, ADR-0014
Decision 5). `start_date`/`end_date` are ordinary Python `datetime.date`
values at this module's own public boundary -- storage as UTC-midnight
`DateTime` is this module's own internal representation
(`product/accounting/models.py`'s own module docstring explains why:
`infra.db` exports no `Date` column type), never a caller-visible detail.

**No `update_period()`** -- once created, a period's own date boundaries
never change (only its `status`, via `close_period()`/`reopen_period()`
below); ADR-0014 Decision 5's own "no period is ever silently created"
discipline extends naturally to "no period's boundaries silently move
either" -- a boundary change could retroactively alter which period an
already-posted entry's `entry_date` falls into, which this module never
does.

**No publish/subscribe wiring here**: this phase's own event boundary is
journal-level only (`product/accounting/journal.py`'s own
`ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE`/`..._REVERSED_EVENT_TYPE`) --
`accounting.period.closed` (named in ADR-0014 Decision 10's broader
event list) is deliberately **not** published by this phase; see this
phase's own implementation report for the exact reasoning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, acquire_tenant_advisory_lock, select, tenant_session_scope

from product.accounting.errors import (
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.models import PERIOD_STATUS_CLOSED, PERIOD_STATUS_OPEN, Period
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import PERIOD_RESOURCE, require


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PeriodView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: Period) -> PeriodView:
    return PeriodView(
        id=row.id,
        tenant_id=row.tenant_id,
        start_date=row.start_date.date(),
        end_date=row.end_date.date(),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_period(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, start_date: date, end_date: date
) -> PeriodView:
    require(actor_user_id, tenant_id, resource=PERIOD_RESOURCE, action="create")
    if end_date < start_date:
        raise AccountingValidationError("end_date must not be before start_date.")

    period_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            session.add(
                Period(
                    id=period_id,
                    tenant_id=tenant_id,
                    start_date=_date_to_utc_midnight(start_date),
                    end_date=_date_to_utc_midnight(end_date),
                    status=PERIOD_STATUS_OPEN,
                )
            )
            session.flush()
    except IntegrityError as exc:
        # The EXCLUDE USING gist constraint (migration
        # 0053_create_accounting_periods_table) -- a period overlapping an
        # existing one for this tenant, translated the same way
        # `product/appointments/booking.py`'s own double-booking
        # `IntegrityError` is translated: the write is simply attempted,
        # never a race-prone "check then insert."
        raise AccountingConflictError("date_range", f"{start_date}..{end_date}") from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Period, period_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.period.created",
        resource_type="accounting.period",
        resource_id=str(period_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, period_id: uuid.UUID) -> Period:
    row = session.get(Period, period_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("period", period_id)
    return row


def get_period(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, period_id: uuid.UUID) -> PeriodView:
    require(actor_user_id, tenant_id, resource=PERIOD_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, period_id)
        session.expunge(row)
    return _to_view(row)


def list_periods(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[PeriodView]:
    require(actor_user_id, tenant_id, resource=PERIOD_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Period)
                .where(Period.tenant_id == tenant_id)
                .order_by(Period.start_date.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def find_period_for_date(session, tenant_id: uuid.UUID, entry_date: date) -> Period | None:
    """Internal lookup used by `product/accounting/journal.py
    ::post_journal_entry()`/`reverse_journal_entry()` -- the OPEN-or-
    CLOSED period (regardless of status; the caller distinguishes "no
    period at all" from "a CLOSED period exists") whose inclusive date
    range contains `entry_date`. Runs on the caller's own already-open
    `session` -- never opens a second `tenant_session_scope()` (this
    function is called from inside the advisory-lock-protected block
    `journal.py` itself manages, per ADR-0014 Decision 5)."""
    target = _date_to_utc_midnight(entry_date)
    return session.execute(
        select(Period).where(
            Period.tenant_id == tenant_id,
            Period.start_date <= target,
            Period.end_date >= target,
        )
    ).scalar_one_or_none()


def close_period(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, period_id: uuid.UUID
) -> PeriodView:
    """Flips `status` to `closed` -- rejects **new** posts/reversals
    targeting this period from now on; does not retroactively invalidate
    anything already posted into it (ADR-0014 Decision 5). Takes the same
    transaction-scoped tenant advisory lock `post_journal_entry()`/
    `reverse_journal_entry()` take on this exact period, before reading
    its current status, so a period cannot be closed mid-post and a post
    cannot land after a close call has started evaluating it (mirrors
    `core.usage.service._consume_quota_in_session()`'s own
    lock-before-read pattern)."""
    require(actor_user_id, tenant_id, resource=PERIOD_RESOURCE, action="manage")
    with tenant_session_scope(tenant_id) as session:
        acquire_tenant_advisory_lock(session, tenant_id, f"accounting.period.{period_id}")
        row = _get_owned_row(session, tenant_id, period_id)
        if row.status == PERIOD_STATUS_CLOSED:
            raise AccountingValidationError(f"period {period_id} is already closed.")
        row.status = PERIOD_STATUS_CLOSED
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.period.closed",
        resource_type="accounting.period",
        resource_id=str(period_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return _to_view(row)


def reopen_period(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, period_id: uuid.UUID
) -> PeriodView:
    """Flips `status` back to `open`. Anything posted while this period
    was previously open remains posted and immutable (Decision 3) --
    reopening only changes whether *new* posts/reversals are accepted
    again, exactly the mirror of `close_period()`."""
    require(actor_user_id, tenant_id, resource=PERIOD_RESOURCE, action="manage")
    with tenant_session_scope(tenant_id) as session:
        acquire_tenant_advisory_lock(session, tenant_id, f"accounting.period.{period_id}")
        row = _get_owned_row(session, tenant_id, period_id)
        if row.status == PERIOD_STATUS_OPEN:
            raise AccountingValidationError(f"period {period_id} is already open.")
        row.status = PERIOD_STATUS_OPEN
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.period.reopened",
        resource_type="accounting.period",
        resource_id=str(period_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return _to_view(row)


__all__ = [
    "PeriodView",
    "close_period",
    "create_period",
    "find_period_for_date",
    "get_period",
    "list_periods",
    "reopen_period",
]
