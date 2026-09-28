"""`product/accounting/periods.py`: period creation, non-overlap, open/
closed lifecycle, tenant isolation, authorization, and the period-lock
concurrency guarantee against `journal.py::post_journal_entry()`
(docs/ROADMAP.md Phase 24, ADR-0014 Decision 5). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.tenancy import TenantStatus, transition_tenant_status
from product.accounting.accounts import create_account
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingConflictError,
    AccountingPeriodClosedError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.journal import JournalLineInput, create_journal_entry, post_journal_entry
from product.accounting.models import PERIOD_STATUS_CLOSED, PERIOD_STATUS_OPEN
from product.accounting.periods import (
    close_period,
    create_period,
    get_period,
    list_periods,
    reopen_period,
)
from product.agency.provisioning import provision_agency, provision_client

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_create_get_list_period() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        period = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        assert period.status == PERIOD_STATUS_OPEN
        assert period.start_date == date(2026, 1, 1)
        assert period.end_date == date(2026, 1, 31)

        fetched = get_period(owner.id, client.tenant_id, period.id)
        assert fetched == period
        assert [p.id for p in list_periods(owner.id, client.tenant_id)] == [period.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_period_rejects_end_before_start() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingValidationError):
            create_period(
                owner.id, client.tenant_id, start_date=date(2026, 2, 1), end_date=date(2026, 1, 1)
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_overlapping_period_rejected_by_database_directly() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        with pytest.raises(AccountingConflictError):
            create_period(
                owner.id,
                client.tenant_id,
                start_date=date(2026, 1, 15),
                end_date=date(2026, 2, 15),
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_adjacent_non_overlapping_periods_both_succeed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        second = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)
        )
        assert second.start_date == date(2026, 2, 1)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_close_and_reopen_period() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        period = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        closed = close_period(owner.id, client.tenant_id, period.id)
        assert closed.status == PERIOD_STATUS_CLOSED

        with pytest.raises(AccountingValidationError):
            close_period(owner.id, client.tenant_id, period.id)

        reopened = reopen_period(owner.id, client.tenant_id, period.id)
        assert reopened.status == PERIOD_STATUS_OPEN
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_closing_period_rejects_new_posts_but_keeps_already_posted_entries() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        period = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        already_posted = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("100")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("100")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, already_posted.id)

        close_period(owner.id, client.tenant_id, period.id)

        new_draft = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 20),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("50")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("50")),
            ],
        )
        with pytest.raises(AccountingPeriodClosedError):
            post_journal_entry(owner.id, client.tenant_id, new_draft.id)

        # The already-posted entry is untouched by the later close.
        from product.accounting.journal import get_journal_entry

        still_posted = get_journal_entry(owner.id, client.tenant_id, already_posted.id)
        assert still_posted.status == "posted"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_periods_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        period = create_period(
            owner.id, client_a.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_period(owner.id, client_b.tenant_id, period.id)
        # The identical date range is free to use in a different tenant.
        other = create_period(
            owner.id, client_b.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        assert other.tenant_id == client_b.tenant_id
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_or_manage_period() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AccountingAccessDeniedError):
            create_period(
                outsider.id,
                client.tenant_id,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            )
        period = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        with pytest.raises(AccountingAccessDeniedError):
            close_period(outsider.id, client.tenant_id, period.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_suspended_tenant_denies_period_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED, actor_user_id=owner.id)
        with pytest.raises(AccountingAccessDeniedError):
            create_period(
                owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
            )
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE, actor_user_id=owner.id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_close_and_post_never_corrupts_state() -> None:
    """Real concurrency, real Postgres: one thread posts a draft entry,
    another closes its covering period, both racing for the same
    `infra.db.acquire_tenant_advisory_lock` key
    (`f"accounting.period.{period_id}"`). Whichever wins, the final state
    must be internally consistent -- never a posted entry against a
    period that "wasn't really open," never a half-closed period. Mirrors
    `tests/telephony/test_inbound_events_integration.py`'s own
    `threading.Barrier`-based concurrency test shape."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        period = create_period(
            owner.id, client.tenant_id, start_date=date(2026, 3, 1), end_date=date(2026, 3, 31)
        )
        draft = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 3, 15),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("25")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("25")),
            ],
        )

        results: dict[str, object] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def _post() -> None:
            try:
                barrier.wait(timeout=5)
                results["post"] = post_journal_entry(owner.id, client.tenant_id, draft.id)
            except Exception as exc:  # noqa: BLE001 -- one of two valid, mutually exclusive outcomes
                results["post_error"] = exc

        def _close() -> None:
            try:
                barrier.wait(timeout=5)
                results["close"] = close_period(owner.id, client.tenant_id, period.id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_post), threading.Thread(target=_close)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors: {errors}"
        from product.accounting.journal import get_journal_entry

        final_entry = get_journal_entry(owner.id, client.tenant_id, draft.id)
        final_period = get_period(owner.id, client.tenant_id, period.id)
        assert final_period.status == PERIOD_STATUS_CLOSED
        if "post_error" in results:
            # Close won the race: the post must have been cleanly rejected,
            # never partially applied.
            assert isinstance(results["post_error"], AccountingPeriodClosedError)
            assert final_entry.status == "draft"
        else:
            # Post won the race: it must have fully succeeded before the
            # close took effect.
            assert final_entry.status == "posted"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
