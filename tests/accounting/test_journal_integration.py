"""`product/accounting/journal.py`: journal-entry lifecycle, double-entry
balance enforcement, immutability, reversal, period resolution,
idempotency, audit, and events (docs/ROADMAP.md Phase 24, ADR-0014
Decisions 2-5 and the journal-only slice of 9-11). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.audit_log import list as list_audit_log
from core.tenancy import TenantStatus, transition_tenant_status
from product.accounting.accounts import create_account, deactivate_account
from product.accounting.errors import (
    AccountingAccessDeniedError,
    AccountingPeriodNotFoundError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.journal import (
    ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE,
    ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE,
    JournalLineInput,
    create_journal_entry,
    get_journal_entry,
    list_journal_entries,
    post_journal_entry,
    reverse_journal_entry,
    update_journal_entry,
    void_journal_entry,
)
from product.accounting.periods import create_period
from product.agency.provisioning import provision_agency, provision_client
from product.foundation.events import subscribe

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _setup(owner_id, tenant_id):
    """Two accounts + one open period covering 2026-01 -- the common
    fixture every test below builds on."""
    cash = create_account(owner_id, tenant_id, code="1000", name="Cash", account_type="asset")
    revenue = create_account(owner_id, tenant_id, code="4000", name="Sales", account_type="revenue")
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
    return cash, revenue


# --- Creation, balanced/unbalanced draft, at-least-two-lines -------------------


def test_create_journal_entry_draft_need_not_be_balanced() -> None:
    """Decision 3: a draft "has no financial effect" and "may be edited...
    freely" -- creation does not enforce sum(debits) == sum(credits)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="eur",
            description="Unbalanced draft, allowed",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("100.00")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("50.00")),
            ],
        )
        assert entry.status == "draft"
        assert entry.currency == "EUR"  # normalized uppercase
        assert len(entry.lines) == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_fewer_than_two_lines() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, _ = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[JournalLineInput(account_id=cash.id, debit_amount=Decimal("10"))],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_line_with_both_sides_zero() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(account_id=cash.id),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_line_with_both_sides_positive() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingValidationError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(
                        account_id=cash.id, debit_amount=Decimal("10"), credit_amount=Decimal("5")
                    ),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_unknown_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, _ = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingReferenceNotFoundError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                    JournalLineInput(account_id=uuid.uuid4(), credit_amount=Decimal("10")),
                ],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_inactive_account() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        deactivate_account(owner.id, client.tenant_id, cash.id)
        with pytest.raises(AccountingValidationError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_journal_entry_rejects_malformed_currency() -> None:
    from product.foundation.values import InvalidCurrencyCodeError

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        with pytest.raises(InvalidCurrencyCodeError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="euros",
                lines=[
                    JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Update / void (draft-only) -------------------------------------------------


def test_update_and_void_draft_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        updated = update_journal_entry(
            owner.id,
            client.tenant_id,
            entry.id,
            description="Corrected memo",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("20")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("20")),
            ],
        )
        assert updated.description == "Corrected memo"
        assert updated.lines[0].debit_amount == Decimal("20.00")

        voided = void_journal_entry(owner.id, client.tenant_id, entry.id)
        assert voided.status == "voided"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Posting: balance enforcement, atomicity, period resolution -----------------


def test_post_balanced_entry_succeeds_and_resolves_period() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("100")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("100")),
            ],
        )
        posted = post_journal_entry(owner.id, client.tenant_id, entry.id)
        assert posted.status == "posted"
        assert posted.period_id is not None
        assert posted.posted_by_user_id == owner.id
        assert posted.posted_at is not None
        assert posted.lines[0].debit_amount == Decimal("100.00")
        assert posted.lines[1].credit_amount == Decimal("100.00")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_unbalanced_entry_rejected_atomically() -> None:
    """The entry must remain fully `draft` -- never partially posted --
    when the balance check fails."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("100")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("40")),
            ],
        )
        with pytest.raises(AccountingValidationError):
            post_journal_entry(owner.id, client.tenant_id, entry.id)

        unchanged = get_journal_entry(owner.id, client.tenant_id, entry.id)
        assert unchanged.status == "draft"
        assert unchanged.period_id is None
        assert unchanged.posted_at is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_with_no_covering_period_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        # No period created at all this time.
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 6, 1),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        with pytest.raises(AccountingPeriodNotFoundError):
            post_journal_entry(owner.id, client.tenant_id, entry.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_post_already_posted_entry_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, entry.id)
        with pytest.raises(AccountingValidationError):
            post_journal_entry(owner.id, client.tenant_id, entry.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Immutability ---------------------------------------------------------------


def test_posted_entry_cannot_be_updated_or_voided() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, entry.id)

        with pytest.raises(AccountingValidationError):
            update_journal_entry(owner.id, client.tenant_id, entry.id, description="edited")
        with pytest.raises(AccountingValidationError):
            void_journal_entry(owner.id, client.tenant_id, entry.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Reversal ---------------------------------------------------------------


def test_reverse_posted_entry_mirrors_lines_and_stays_balanced() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        original = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("75.50")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("75.50")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, original.id)

        reversal = reverse_journal_entry(
            owner.id, client.tenant_id, original.id, reversal_entry_date=date(2026, 1, 20)
        )
        assert reversal.status == "posted"
        assert reversal.reverses_entry_id == original.id
        total_debits = sum((line.debit_amount for line in reversal.lines), Decimal("0"))
        total_credits = sum((line.credit_amount for line in reversal.lines), Decimal("0"))
        assert total_debits == total_credits == Decimal("75.50")
        # Mirrored: cash's original debit becomes a credit on the reversal.
        cash_line = next(line for line in reversal.lines if line.account_id == cash.id)
        assert cash_line.credit_amount == Decimal("75.50")
        assert cash_line.debit_amount == Decimal("0.00")

        original_after = get_journal_entry(owner.id, client.tenant_id, original.id)
        assert original_after.status == "reversed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_non_posted_entry_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        draft = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        with pytest.raises(AccountingValidationError):
            reverse_journal_entry(owner.id, client.tenant_id, draft.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_twice_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        original = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, original.id)
        reverse_journal_entry(
            owner.id, client.tenant_id, original.id, reversal_entry_date=date(2026, 1, 20)
        )
        with pytest.raises(AccountingValidationError):
            reverse_journal_entry(
                owner.id, client.tenant_id, original.id, reversal_entry_date=date(2026, 1, 21)
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reverse_respects_period_locking() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        original = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, original.id)
        # No period covers a reversal dated in June.
        with pytest.raises(AccountingPeriodNotFoundError):
            reverse_journal_entry(
                owner.id, client.tenant_id, original.id, reversal_entry_date=date(2026, 6, 1)
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Idempotency ---------------------------------------------------------------


def test_repeated_post_with_same_idempotency_key_does_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        key = f"post-{uuid.uuid4()}"
        first = post_journal_entry(owner.id, client.tenant_id, entry.id, idempotency_key=key)
        second = post_journal_entry(owner.id, client.tenant_id, entry.id, idempotency_key=key)
        assert first.posted_at == second.posted_at
        assert first.period_id == second.period_id

        entries = list_audit_log(
            client.tenant_id,
            resource_type="accounting.journal_entry",
            resource_id=str(entry.id),
        )
        posted_audit_entries = [e for e in entries if e.action == "accounting.journal_entry.posted"]
        assert len(posted_audit_entries) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_repeated_reverse_with_same_idempotency_key_does_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        original = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, original.id)
        key = f"reverse-{uuid.uuid4()}"
        first = reverse_journal_entry(
            owner.id,
            client.tenant_id,
            original.id,
            reversal_entry_date=date(2026, 1, 20),
            idempotency_key=key,
        )
        second = reverse_journal_entry(
            owner.id,
            client.tenant_id,
            original.id,
            reversal_entry_date=date(2026, 1, 20),
            idempotency_key=key,
        )
        assert first.id == second.id

        all_entries = list_journal_entries(owner.id, client.tenant_id)
        reversal_entries = [e for e in all_entries if e.reverses_entry_id == original.id]
        assert len(reversal_entries) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Audit -----------------------------------------------------------------


def test_creation_posting_and_reversal_are_all_audited() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, entry.id)
        reverse_journal_entry(
            owner.id, client.tenant_id, entry.id, reversal_entry_date=date(2026, 1, 20)
        )

        entries = list_audit_log(
            client.tenant_id, resource_type="accounting.journal_entry", resource_id=str(entry.id)
        )
        actions = {e.action for e in entries}
        assert "accounting.journal_entry.created" in actions
        assert "accounting.journal_entry.posted" in actions
        assert "accounting.journal_entry.reversed" in actions
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Events -----------------------------------------------------------------


def test_post_and_reverse_publish_expected_events_only() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received_types: list[str] = []

    def _handler(event) -> None:
        received_types.append(event.type)

    subscribe(ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE, _handler)
    subscribe(ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE, _handler)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        post_journal_entry(owner.id, client.tenant_id, entry.id)
        reverse_journal_entry(
            owner.id, client.tenant_id, entry.id, reversal_entry_date=date(2026, 1, 20)
        )

        assert received_types == [
            ACCOUNTING_JOURNAL_POSTED_EVENT_TYPE,
            ACCOUNTING_JOURNAL_REVERSED_EVENT_TYPE,
        ]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation / authorization ---------------------------------------


def test_journal_entries_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client_a.tenant_id)
        entry = create_journal_entry(
            owner.id,
            client_a.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        with pytest.raises(AccountingReferenceNotFoundError):
            get_journal_entry(owner.id, client_b.tenant_id, entry.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_unrelated_actor_cannot_create_or_post() -> None:
    owner = make_user()
    outsider = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        with pytest.raises(AccountingAccessDeniedError):
            create_journal_entry(
                outsider.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
        entry = create_journal_entry(
            owner.id,
            client.tenant_id,
            entry_date=date(2026, 1, 10),
            currency="EUR",
            lines=[
                JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
            ],
        )
        with pytest.raises(AccountingAccessDeniedError):
            post_journal_entry(outsider.id, client.tenant_id, entry.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, outsider.id)


def test_suspended_tenant_denies_journal_mutation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash, revenue = _setup(owner.id, client.tenant_id)
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED, actor_user_id=owner.id)
        with pytest.raises(AccountingAccessDeniedError):
            create_journal_entry(
                owner.id,
                client.tenant_id,
                entry_date=date(2026, 1, 10),
                currency="EUR",
                lines=[
                    JournalLineInput(account_id=cash.id, debit_amount=Decimal("10")),
                    JournalLineInput(account_id=revenue.id, credit_amount=Decimal("10")),
                ],
            )
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE, actor_user_id=owner.id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
