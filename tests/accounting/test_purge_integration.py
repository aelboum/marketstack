"""`product/accounting/purge.py`: the documented no-op purge participant
(ADR-0014 Decision 9). Real disposable Postgres. Marked `integration`,
excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from product.accounting.accounts import create_account
from product.accounting.journal import JournalLineInput, create_journal_entry, post_journal_entry
from product.accounting.periods import create_period
from product.accounting.purge import AccountingDataPurgeParticipant
from product.agency.provisioning import provision_agency, provision_client

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_purge_is_a_documented_no_op() -> None:
    """Even a posted journal entry survives a tenant purge call --
    Decision 9's own "no accounting row is ever deleted by tenant purge,"
    verified directly, not merely asserted by the docstring."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        cash = create_account(
            owner.id, client.tenant_id, code="1000", name="Cash", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
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
        post_journal_entry(owner.id, client.tenant_id, entry.id)

        participant = AccountingDataPurgeParticipant()
        assert participant.name == "accounting.*"
        # Documented no-op: does not raise, does not delete anything.
        participant.purge_tenant_data(client.tenant_id)
        participant.purge_tenant_data(client.tenant_id)  # idempotent, by contract

        from product.accounting.accounts import list_accounts
        from product.accounting.journal import list_journal_entries

        assert len(list_accounts(owner.id, client.tenant_id)) == 2
        assert len(list_journal_entries(owner.id, client.tenant_id)) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
