"""HTTP-level integration tests for the Accounting API exposure
(`product/accounting/routes.py`), through a real FastAPI `TestClient` and
a real, already-migrated PostgreSQL database. Mirrors
`tests/billing/test_routes_integration.py`'s own shape.

The original Phase 25 overdue-invoices route keeps its own dedicated
tests in `tests/accounting/test_routes_integration.py` (unchanged); this
module covers every route added by the API exposure phase: routing and
OpenAPI presence, authentication, the non-enumerating tenant boundary,
RBAC (a `member` lacking an owner-only action), representative CRUD and
lifecycle over HTTP for every resource, and the HTTP error mapping
(400/404/409/422). Business rules themselves stay covered by the
existing service-level suites -- these tests prove the HTTP adapters
reach them correctly, never re-test the accounting logic.

Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity import add_tenant_membership
from core.identity.sessions import issue_session
from core.rbac import RoleScope, assign_role
from fastapi.testclient import TestClient
from product.accounting.accounts import get_account
from product.accounting.contacts import tag_contact_role
from product.accounting.periods import create_period
from product.accounting.routes import MAX_STATEMENT_CSV_LENGTH
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.api.main import create_app
from product.crm.contacts import create_contact

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_BASE = "/v1/accounting/tenants"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(
        tenant_id, user_id, caller=SystemCaller(SystemAuthority.PROVISIONING)
    )
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, caller=UserCaller(owner_id)
    )


def _auth(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _api() -> TestClient:
    return TestClient(create_app())


def _create_account(api, headers, tenant_id, code, name, account_type) -> dict:
    response = api.post(
        f"{_BASE}/{tenant_id}/accounts",
        json={"code": code, "name": name, "account_type": account_type},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _customer(owner_id, tenant_id):
    contact = create_contact(owner_id, tenant_id, first_name="Jane", last_name="Customer")
    tag_contact_role(owner_id, tenant_id, contact.id, role="customer")
    return contact


def _supplier(owner_id, tenant_id):
    contact = create_contact(owner_id, tenant_id, first_name="Acme", last_name="Supplies")
    tag_contact_role(owner_id, tenant_id, contact.id, role="supplier")
    return contact


# --- Routing / OpenAPI ---------------------------------------------------------------


def test_accounting_routes_are_in_the_openapi_schema() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    expected = {
        ("post", "/accounts"),
        ("get", "/accounts"),
        ("patch", "/accounts/{account_id}"),
        ("post", "/periods/{period_id}/close"),
        ("post", "/journal-entries/{entry_id}/post"),
        ("post", "/journal-entries/{entry_id}/reverse"),
        ("post", "/tax-codes"),
        ("post", "/contact-roles"),
        ("post", "/invoices"),
        ("get", "/invoices/overdue"),
        ("post", "/invoices/{invoice_id}/post"),
        ("post", "/invoices/{invoice_id}/credit-notes"),
        ("post", "/bills/{bill_id}/post"),
        ("post", "/payments/{payment_id}/allocations"),
        ("post", "/payment-allocations/{allocation_id}/reverse"),
        ("post", "/bank-accounts/{bank_account_id}/statements"),
        ("post", "/bank-statement-lines/{line_id}/match"),
        ("post", "/bank-statement-lines/{line_id}/assign-account"),
    }
    for method, suffix in expected:
        path = f"{_BASE}/{{tenant_id}}{suffix}"
        assert path in paths, path
        assert method in paths[path], (method, path)


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", "/accounts"),
        ("post", "/accounts"),
        ("get", "/journal-entries"),
        ("post", "/invoices"),
        ("post", "/payments"),
        ("get", "/bank-accounts"),
    ],
)
def test_unauthenticated_accounting_requests_are_401(method: str, suffix: str) -> None:
    response = _api().request(method.upper(), f"{_BASE}/{uuid.uuid4()}{suffix}", json={})
    assert response.status_code == 401


# --- Tenant isolation / RBAC -----------------------------------------------------------


def test_cross_tenant_reads_and_writes_are_non_enumerating_404() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        api = _api()
        account_a = _create_account(
            api, _auth(owner_a.id), client_a.tenant_id, "1100", "AR", "asset"
        )
        headers_b = _auth(owner_b.id)

        # Owner B addressing tenant A directly: no permission there.
        assert (
            api.get(f"{_BASE}/{client_a.tenant_id}/accounts", headers=headers_b).status_code == 404
        )
        assert (
            api.post(
                f"{_BASE}/{client_a.tenant_id}/accounts",
                json={"code": "9999", "name": "Injected", "account_type": "asset"},
                headers=headers_b,
            ).status_code
            == 404
        )
        assert (
            api.get(
                f"{_BASE}/{client_a.tenant_id}/accounts/{account_a['id']}", headers=headers_b
            ).status_code
            == 404
        )

        # Owner B addressing its own tenant, but with tenant A's record id.
        assert (
            api.get(
                f"{_BASE}/{client_b.tenant_id}/accounts/{account_a['id']}", headers=headers_b
            ).status_code
            == 404
        )
        assert (
            api.patch(
                f"{_BASE}/{client_b.tenant_id}/accounts/{account_a['id']}",
                json={"name": "Hijacked"},
                headers=headers_b,
            ).status_code
            == 404
        )
        assert (
            api.post(
                f"{_BASE}/{client_b.tenant_id}/accounts/{account_a['id']}/deactivate",
                headers=headers_b,
            ).status_code
            == 404
        )

        unchanged = get_account(owner_a.id, client_a.tenant_id, uuid.UUID(account_a["id"]))
        assert unchanged.name == "AR"
        assert unchanged.is_active is True
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_member_is_denied_owner_only_actions_over_http() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        api = _api()
        member_headers = _auth(member.id)
        period = api.post(
            f"{_BASE}/{client.tenant_id}/periods",
            json={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            headers=member_headers,
        )
        assert period.status_code == 201, period.text

        # `accounting.period.manage` is owner-only.
        denied = api.post(
            f"{_BASE}/{client.tenant_id}/periods/{period.json()['id']}/close",
            headers=member_headers,
        )
        assert denied.status_code == 404

        closed = api.post(
            f"{_BASE}/{client.tenant_id}/periods/{period.json()['id']}/close",
            headers=_auth(owner.id),
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Chart of accounts / periods -----------------------------------------------------------


def test_chart_of_accounts_crud_and_error_mapping_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        base = f"{_BASE}/{client.tenant_id}/accounts"
        created = _create_account(api, headers, client.tenant_id, "4000", "Sales", "revenue")
        assert created["account_type"] == "revenue"
        assert created["is_active"] is True

        listed = api.get(base, headers=headers)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [created["id"]]

        fetched = api.get(f"{base}/{created['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["code"] == "4000"

        renamed = api.patch(f"{base}/{created['id']}", json={"name": "Revenue"}, headers=headers)
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Revenue"

        deactivated = api.post(f"{base}/{created['id']}/deactivate", headers=headers)
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False
        reactivated = api.post(f"{base}/{created['id']}/reactivate", headers=headers)
        assert reactivated.json()["is_active"] is True

        duplicate = api.post(
            base,
            json={"code": "4000", "name": "Again", "account_type": "revenue"},
            headers=headers,
        )
        assert duplicate.status_code == 409
        assert str(client.tenant_id) not in duplicate.text

        bad_type = api.post(
            base, json={"code": "4100", "name": "X", "account_type": "nonsense"}, headers=headers
        )
        assert bad_type.status_code == 400

        missing_field = api.post(base, json={"code": "4200"}, headers=headers)
        assert missing_field.status_code == 422

        unknown = api.get(f"{base}/{uuid.uuid4()}", headers=headers)
        assert unknown.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_period_lifecycle_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        base = f"{_BASE}/{client.tenant_id}/periods"
        created = api.post(
            base, json={"start_date": "2026-01-01", "end_date": "2026-12-31"}, headers=headers
        )
        assert created.status_code == 201
        period_id = created.json()["id"]
        assert created.json()["status"] == "open"

        assert [row["id"] for row in api.get(base, headers=headers).json()] == [period_id]
        assert api.get(f"{base}/{period_id}", headers=headers).json()["end_date"] == "2026-12-31"
        assert api.post(f"{base}/{period_id}/close", headers=headers).json()["status"] == "closed"
        assert api.post(f"{base}/{period_id}/reopen", headers=headers).json()["status"] == "open"

        inverted = api.post(
            base, json={"start_date": "2027-12-31", "end_date": "2027-01-01"}, headers=headers
        )
        assert inverted.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Journal entries ---------------------------------------------------------------------


def test_journal_entry_lifecycle_idempotency_and_period_errors_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        cash = _create_account(api, headers, client.tenant_id, "1000", "Cash", "asset")
        equity = _create_account(api, headers, client.tenant_id, "3000", "Equity", "equity")
        base = f"{_BASE}/{client.tenant_id}/journal-entries"
        lines = [
            {"account_id": cash["id"], "debit_amount": "250.00"},
            {"account_id": equity["id"], "credit_amount": "250.00"},
        ]

        # No period covers 2026 yet: posting must be a 409, not a 500.
        orphan = api.post(
            base,
            json={"entry_date": "2026-03-01", "currency": "EUR", "lines": lines},
            headers=headers,
        )
        assert orphan.status_code == 201
        no_period = api.post(f"{base}/{orphan.json()['id']}/post", headers=headers)
        assert no_period.status_code == 409
        assert no_period.json()["detail"] == "No accounting period covers that date."

        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        draft = api.post(
            base,
            json={
                "entry_date": "2026-03-01",
                "currency": "EUR",
                "lines": lines,
                "description": "Capital",
            },
            headers=headers,
        )
        assert draft.status_code == 201
        entry_id = draft.json()["id"]
        assert draft.json()["status"] == "draft"
        assert len(draft.json()["lines"]) == 2

        patched = api.patch(
            f"{base}/{entry_id}", json={"description": "Opening capital"}, headers=headers
        )
        assert patched.status_code == 200
        assert patched.json()["description"] == "Opening capital"

        key = f"post-{uuid.uuid4()}"
        posted = api.post(f"{base}/{entry_id}/post", json={"idempotency_key": key}, headers=headers)
        assert posted.status_code == 200
        assert posted.json()["status"] == "posted"
        replay = api.post(f"{base}/{entry_id}/post", json={"idempotency_key": key}, headers=headers)
        assert replay.status_code == 200
        assert replay.json()["id"] == entry_id

        reversed_entry = api.post(f"{base}/{entry_id}/reverse", json={}, headers=headers)
        assert reversed_entry.status_code == 200
        assert reversed_entry.json()["reverses_entry_id"] == entry_id

        # An unbalanced *draft* is allowed by design (journal.py builds an
        # entry up incrementally); balance is enforced only at posting.
        unbalanced = api.post(
            base,
            json={
                "entry_date": "2026-03-02",
                "currency": "EUR",
                "lines": [
                    {"account_id": cash["id"], "debit_amount": "10.00"},
                    {"account_id": equity["id"], "credit_amount": "9.00"},
                ],
            },
            headers=headers,
        )
        assert unbalanced.status_code == 201
        rejected = api.post(f"{base}/{unbalanced.json()['id']}/post", headers=headers)
        assert rejected.status_code == 400

        listed = api.get(base, headers=headers)
        assert listed.status_code == 200
        assert entry_id in {row["id"] for row in listed.json()}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tax codes / contact roles / invoices / credit notes / payments -----------------------


def test_invoice_payment_and_credit_note_workflow_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        t = client.tenant_id
        receivable = _create_account(api, headers, t, "1100", "AR", "asset")
        revenue = _create_account(api, headers, t, "4000", "Sales", "revenue")
        vat = _create_account(api, headers, t, "2200", "VAT Payable", "liability")
        create_period(owner.id, t, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))

        contact = create_contact(owner.id, t, first_name="Jane", last_name="Customer")
        tagged = api.post(
            f"{_BASE}/{t}/contact-roles",
            json={"contact_id": str(contact.id), "role": "customer"},
            headers=headers,
        )
        assert tagged.status_code == 201
        assert (
            api.get(f"{_BASE}/{t}/contact-roles/{contact.id}", headers=headers).json()["role"]
            == "customer"
        )
        assert [
            row["contact_id"]
            for row in api.get(
                f"{_BASE}/{t}/contact-roles", params={"role": "customer"}, headers=headers
            ).json()
        ] == [str(contact.id)]

        tax_code = api.post(
            f"{_BASE}/{t}/tax-codes",
            json={
                "code": "NL-STD",
                "name": "Standard VAT",
                "rate_percent": "21.0",
                "tax_type": "sales",
                "tax_account_id": vat["id"],
            },
            headers=headers,
        )
        assert tax_code.status_code == 201
        assert [row["id"] for row in api.get(f"{_BASE}/{t}/tax-codes", headers=headers).json()] == [
            tax_code.json()["id"]
        ]

        invoice = api.post(
            f"{_BASE}/{t}/invoices",
            json={
                "contact_id": str(contact.id),
                "receivable_account_id": receivable["id"],
                "currency": "EUR",
                "issue_date": "2026-01-10",
                "due_date": "2026-01-24",
                "lines": [
                    {
                        "account_id": revenue["id"],
                        "description": "Consulting",
                        "quantity": "2",
                        "unit_price": "100.00",
                        "tax_code_id": tax_code.json()["id"],
                    }
                ],
            },
            headers=headers,
        )
        assert invoice.status_code == 201, invoice.text
        invoice_id = invoice.json()["id"]
        assert invoice.json()["status"] == "draft"
        assert invoice.json()["total"] == "242.00"
        assert invoice.json()["invoice_number"] is None

        patched = api.patch(
            f"{_BASE}/{t}/invoices/{invoice_id}", json={"description": "Jan work"}, headers=headers
        )
        assert patched.json()["description"] == "Jan work"

        posted = api.post(f"{_BASE}/{t}/invoices/{invoice_id}/post", headers=headers)
        assert posted.status_code == 200
        assert posted.json()["status"] == "posted"
        assert posted.json()["invoice_number"] is not None

        drafts = api.get(f"{_BASE}/{t}/invoices", params={"status": "draft"}, headers=headers)
        assert drafts.status_code == 200
        assert drafts.json() == []
        posted_list = api.get(f"{_BASE}/{t}/invoices", params={"status": "posted"}, headers=headers)
        assert [row["id"] for row in posted_list.json()] == [invoice_id]

        # The pre-existing overdue route still resolves (not shadowed by
        # `/invoices/{invoice_id}`) and returns its original summary shape.
        overdue = api.get(f"{_BASE}/{t}/invoices/overdue", headers=headers)
        assert overdue.status_code == 200
        assert [row["id"] for row in overdue.json()] == [invoice_id]
        assert set(overdue.json()[0]) == {
            "id",
            "tenant_id",
            "invoice_number",
            "contact_id",
            "currency",
            "status",
            "due_date",
            "total",
            "outstanding_amount",
        }

        payment = api.post(
            f"{_BASE}/{t}/payments",
            json={
                "contact_id": str(contact.id),
                "direction": "inbound",
                "amount": "100.00",
                "currency": "EUR",
                "idempotency_key": f"pay-{uuid.uuid4()}",
            },
            headers=headers,
        )
        assert payment.status_code == 201, payment.text
        payment_id = payment.json()["id"]

        allocation = api.post(
            f"{_BASE}/{t}/payments/{payment_id}/allocations",
            json={"document_type": "invoice", "document_id": invoice_id, "amount": "100.00"},
            headers=headers,
        )
        assert allocation.status_code == 201, allocation.text
        assert (
            api.get(f"{_BASE}/{t}/invoices/{invoice_id}", headers=headers).json()[
                "outstanding_amount"
            ]
            == "142.00"
        )
        allocations = api.get(f"{_BASE}/{t}/invoices/{invoice_id}/allocations", headers=headers)
        assert [row["id"] for row in allocations.json()] == [allocation.json()["id"]]
        assert (
            api.get(f"{_BASE}/{t}/payments/{payment_id}", headers=headers).json()[
                "unallocated_amount"
            ]
            == "0.00"
        )

        over_allocation = api.post(
            f"{_BASE}/{t}/payments/{payment_id}/allocations",
            json={"document_type": "invoice", "document_id": invoice_id, "amount": "1.00"},
            headers=headers,
        )
        assert over_allocation.status_code == 400

        reversal = api.post(
            f"{_BASE}/{t}/payment-allocations/{allocation.json()['id']}/reverse", headers=headers
        )
        assert reversal.status_code == 200
        assert reversal.json()["reverses_allocation_id"] == allocation.json()["id"]

        credit_note = api.post(
            f"{_BASE}/{t}/invoices/{invoice_id}/credit-notes",
            json={
                "currency": "EUR",
                "issue_date": "2026-01-20",
                "lines": [
                    {
                        "account_id": revenue["id"],
                        "description": "Discount",
                        "quantity": "1",
                        "unit_price": "10.00",
                    }
                ],
            },
            headers=headers,
        )
        assert credit_note.status_code == 201, credit_note.text
        credit_note_id = credit_note.json()["id"]
        assert [
            row["id"]
            for row in api.get(
                f"{_BASE}/{t}/invoices/{invoice_id}/credit-notes", headers=headers
            ).json()
        ] == [credit_note_id]
        posted_credit = api.post(f"{_BASE}/{t}/credit-notes/{credit_note_id}/post", headers=headers)
        assert posted_credit.status_code == 200
        assert posted_credit.json()["status"] == "posted"
        assert (
            api.get(f"{_BASE}/{t}/credit-notes/{credit_note_id}", headers=headers).json()[
                "credit_note_number"
            ]
            is not None
        )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_idempotency_key_reuse_for_a_different_payment_is_409() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        t = client.tenant_id
        contact = _customer(owner.id, t)
        key = f"pay-{uuid.uuid4()}"
        body = {
            "contact_id": str(contact.id),
            "direction": "inbound",
            "amount": "50.00",
            "currency": "EUR",
            "idempotency_key": key,
        }
        first = api.post(f"{_BASE}/{t}/payments", json=body, headers=headers)
        assert first.status_code == 201
        replay = api.post(f"{_BASE}/{t}/payments", json=body, headers=headers)
        assert replay.status_code == 201
        assert replay.json()["id"] == first.json()["id"]
        assert len(api.get(f"{_BASE}/{t}/payments", headers=headers).json()) == 1

        conflicting = api.post(
            f"{_BASE}/{t}/payments", json={**body, "amount": "60.00"}, headers=headers
        )
        assert conflicting.status_code == 409
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Bills ----------------------------------------------------------------------------------


def test_bill_lifecycle_with_owner_only_posting_over_http() -> None:
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _add_member(owner.id, client.tenant_id, member.id)
        api = _api()
        owner_headers = _auth(owner.id)
        member_headers = _auth(member.id)
        t = client.tenant_id
        payable = _create_account(api, owner_headers, t, "2000", "AP", "liability")
        expense = _create_account(api, owner_headers, t, "6000", "Office", "expense")
        create_period(owner.id, t, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        supplier = _supplier(owner.id, t)

        bill = api.post(
            f"{_BASE}/{t}/bills",
            json={
                "contact_id": str(supplier.id),
                "supplier_reference": "SUP-001",
                "payable_account_id": payable["id"],
                "currency": "EUR",
                "bill_date": "2026-02-01",
                "due_date": "2026-02-15",
                "lines": [
                    {
                        "account_id": expense["id"],
                        "description": "Paper",
                        "quantity": "1",
                        "unit_price": "40.00",
                    }
                ],
            },
            headers=member_headers,
        )
        assert bill.status_code == 201, bill.text
        bill_id = bill.json()["id"]
        assert api.get(f"{_BASE}/{t}/bills/{bill_id}", headers=member_headers).status_code == 200

        # `accounting.bill.post` is owner-only (ADR-0014 Decision 13).
        assert (
            api.post(f"{_BASE}/{t}/bills/{bill_id}/post", headers=member_headers).status_code == 404
        )
        posted = api.post(f"{_BASE}/{t}/bills/{bill_id}/post", headers=owner_headers)
        assert posted.status_code == 200
        assert posted.json()["status"] == "posted"
        assert [
            row["id"]
            for row in api.get(
                f"{_BASE}/{t}/bills", params={"status": "posted"}, headers=owner_headers
            ).json()
        ] == [bill_id]
        assert (
            api.get(f"{_BASE}/{t}/bills/{bill_id}/allocations", headers=owner_headers).json() == []
        )

        # A posted bill cannot be voided (only drafts can) -- a 400.
        assert (
            api.post(f"{_BASE}/{t}/bills/{bill_id}/void", headers=owner_headers).status_code == 400
        )
        cancelled = api.post(
            f"{_BASE}/{t}/bills/{bill_id}/cancel",
            json={"cancellation_date": "2026-02-20"},
            headers=owner_headers,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


# --- Banking ------------------------------------------------------------------------------


def test_bank_import_and_reconciliation_over_http() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = _api()
        headers = _auth(owner.id)
        t = client.tenant_id
        bank_ledger = _create_account(api, headers, t, "1000", "Main Bank", "asset")
        expense = _create_account(api, headers, t, "5000", "Office Expense", "expense")
        create_period(owner.id, t, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))

        bank_account = api.post(
            f"{_BASE}/{t}/bank-accounts",
            json={"ledger_account_id": bank_ledger["id"], "name": "Main", "currency": "EUR"},
            headers=headers,
        )
        assert bank_account.status_code == 201, bank_account.text
        bank_account_id = bank_account.json()["id"]
        assert [
            row["id"] for row in api.get(f"{_BASE}/{t}/bank-accounts", headers=headers).json()
        ] == [bank_account_id]
        assert (
            api.get(f"{_BASE}/{t}/bank-accounts/{bank_account_id}", headers=headers).status_code
            == 200
        )

        statement = api.post(
            f"{_BASE}/{t}/bank-accounts/{bank_account_id}/statements",
            json={
                "csv_text": (
                    "date,amount,description,reference\n2026-01-13,-50.00,Office supplies,SUP-1"
                ),
                "period_start_date": "2026-01-01",
                "period_end_date": "2026-01-31",
            },
            headers=headers,
        )
        assert statement.status_code == 201, statement.text
        assert statement.json()["imported_line_count"] == 1
        statement_id = statement.json()["id"]

        lines = api.get(
            f"{_BASE}/{t}/bank-statements/{statement_id}/lines",
            params={"status": "unmatched"},
            headers=headers,
        )
        assert lines.status_code == 200
        assert len(lines.json()) == 1
        line_id = lines.json()[0]["id"]

        suggestions = api.get(
            f"{_BASE}/{t}/bank-statement-lines/{line_id}/match-suggestions", headers=headers
        )
        assert suggestions.status_code == 200
        assert isinstance(suggestions.json(), list)

        assigned = api.post(
            f"{_BASE}/{t}/bank-statement-lines/{line_id}/assign-account",
            json={"account_id": expense["id"]},
            headers=headers,
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["status"] == "reconciled"
        assert assigned.json()["journal_entry_id"] is not None

        bad_header = api.post(
            f"{_BASE}/{t}/bank-accounts/{bank_account_id}/statements",
            json={
                "csv_text": "wrong,header\n1,2",
                "period_start_date": "2026-01-01",
                "period_end_date": "2026-01-31",
            },
            headers=headers,
        )
        assert bad_header.status_code == 400

        oversized = api.post(
            f"{_BASE}/{t}/bank-accounts/{bank_account_id}/statements",
            json={
                "csv_text": "x" * (MAX_STATEMENT_CSV_LENGTH + 1),
                "period_start_date": "2026-01-01",
                "period_end_date": "2026-01-31",
            },
            headers=headers,
        )
        assert oversized.status_code == 422
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
