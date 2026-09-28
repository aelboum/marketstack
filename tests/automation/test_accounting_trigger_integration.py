"""Proves `accounting.invoice.posted` is a real, usable Automation
trigger (docs/ROADMAP.md Phase 25 completion remediation) -- the exact
chain the Phase 25 Definition of Done requires: a real accounting
operation publishes a real domain event, the existing
`product.automation` trigger dispatcher (unmodified, the same mechanism
already wired for CRM/Appointments/Marketing/Websites/Telephony events)
picks it up, and a real, observable product effect results -- a `Task` is
actually created, and the run is recorded as success. Never a test that
merely calls the consumer directly or asserts an event-type string
exists.

Mirrors `tests/automation/test_dispatcher_integration.py
::test_appointment_completed_trigger_fires_action_end_to_end()`'s own
shape exactly (a new file, not an edit to that one, to avoid touching a
file with unrelated concurrent in-progress changes). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from infra.db import session_scope, tenant_session_scope
from product.accounting import event_handlers as _accounting_event_handlers  # noqa: F401
from product.accounting.accounts import create_account
from product.accounting.contacts import tag_contact_role
from product.accounting.invoices import InvoiceLineInput, create_invoice, post_invoice
from product.accounting.periods import create_period
from product.agency.provisioning import provision_agency, provision_client
from product.automation import event_handlers as _automation_event_handlers  # noqa: F401
from product.automation.dispatcher import TRIGGER_EVENT_TYPES
from product.automation.models import RUN_STATUS_SUCCESS
from product.automation.workflows import create_workflow, list_workflow_runs
from product.crm import event_handlers as _crm_event_handlers  # noqa: F401
from product.crm.activities import TaskView, list_activities
from product.crm.contacts import create_contact
from sqlalchemy import text

from tests.automation._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_ACCOUNTING_TABLES_LEAF_TO_ROOT = (
    "invoice_lines",
    "invoices",
    "journal_lines",
    "journal_entries",
    "periods",
    "accounts",
    "contact_profiles",
)


def _cleanup_accounting_rows(tenant_id: uuid.UUID) -> None:
    """One-off extension for this file's own cross-domain tests, which
    create real `accounting.*` rows that `tests/automation/_cleanup.py`'s
    own `cleanup_tenant_tree()` does not know about -- mirrors
    `tests/automation/test_dispatcher_integration.py
    ::_cleanup_appointments_rows()`'s identical precedent. Must run
    *before* the base `cleanup_tenant_tree()`'s own `DELETE FROM
    crm.contacts` -- `accounting.contact_profiles`/`accounting.invoices`
    both carry a `RESTRICT` FK to it (ADR-0014 Decision 6 addendum)."""
    with tenant_session_scope(tenant_id) as session:
        for table in _ACCOUNTING_TABLES_LEAF_TO_ROOT:
            session.execute(
                text(f"DELETE FROM accounting.{table} WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
    with session_scope() as session:
        session.execute(
            text("DELETE FROM core.idempotency_records WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _post_a_real_invoice(owner_id, tenant_id):
    """The full Phase 25 accounting operation this trigger must react to
    -- a real invoice, created and posted through the unmodified
    `product.accounting.invoices` service layer, not a hand-built event."""
    receivable = create_account(
        owner_id, tenant_id, code="1100", name="Accounts Receivable", account_type="asset"
    )
    revenue = create_account(owner_id, tenant_id, code="4000", name="Sales", account_type="revenue")
    create_period(owner_id, tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    contact = create_contact(owner_id, tenant_id, first_name="Jane", last_name="Customer")
    tag_contact_role(owner_id, tenant_id, contact.id, role="customer")
    invoice = create_invoice(
        owner_id,
        tenant_id,
        contact_id=contact.id,
        receivable_account_id=receivable.id,
        currency="EUR",
        issue_date=date(2026, 1, 10),
        due_date=date(2026, 1, 24),
        lines=[
            InvoiceLineInput(
                account_id=revenue.id,
                description="Consulting",
                quantity=Decimal("1"),
                unit_price=Decimal("250"),
            )
        ],
    )
    posted = post_invoice(owner_id, tenant_id, invoice.id)
    return posted, contact


def test_invoice_posted_is_a_registered_trigger_type() -> None:
    """Sanity check on the wiring itself, not a substitute for the real
    end-to-end test below -- `create_workflow()`'s own
    `VALID_TRIGGER_TYPES` is derived directly from
    `product.automation.dispatcher.TRIGGER_EVENT_TYPES`
    (`product/automation/workflows.py`), so this also fails loudly if the
    trigger is ever accidentally removed from that tuple."""
    assert "accounting.invoice.posted" in TRIGGER_EVENT_TYPES


def test_invoice_posted_trigger_fires_action_end_to_end() -> None:
    """The real chain: post_invoice() -> accounting.invoice.posted ->
    the existing, unmodified automation dispatcher -> create_task
    (an existing action, unmodified) -- a real Task is created for the
    invoice's own contact, and the run is recorded as success."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        workflow = create_workflow(
            owner.id,
            client.tenant_id,
            name="Task on invoice posted",
            trigger_type="accounting.invoice.posted",
            action_type="create_task",
            action_config={"title": "Follow up after invoicing"},
        )

        posted, contact = _post_a_real_invoice(owner.id, client.tenant_id)

        runs = list_workflow_runs(owner.id, client.tenant_id, workflow.id)
        assert len(runs) == 1
        assert runs[0].status == RUN_STATUS_SUCCESS

        activities = list_activities(owner.id, client.tenant_id, contact_id=contact.id)
        assert any(
            isinstance(a, TaskView) and a.title == "Follow up after invoicing" for a in activities
        )
    finally:
        _cleanup_accounting_rows(client.tenant_id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_invoice_posted_trigger_is_tenant_isolated() -> None:
    """A workflow configured in tenant B must never fire for an invoice
    posted in tenant A -- the dispatcher scopes every lookup by
    `event.tenant_id` (the publisher's own real tenant context), never a
    tenant id read out of the event payload (module docstring of
    `product/automation/dispatcher.py`)."""
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        workflow_b = create_workflow(
            owner.id,
            client_b.tenant_id,
            name="Task on invoice posted (tenant B)",
            trigger_type="accounting.invoice.posted",
            action_type="create_task",
            action_config={"title": "Should never fire for tenant A"},
        )

        _post_a_real_invoice(owner.id, client_a.tenant_id)

        runs = list_workflow_runs(owner.id, client_b.tenant_id, workflow_b.id)
        assert runs == []
    finally:
        _cleanup_accounting_rows(client_a.tenant_id)
        _cleanup_accounting_rows(client_b.tenant_id)
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)
