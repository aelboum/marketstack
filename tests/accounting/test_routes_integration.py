"""HTTP-level integration tests for `product/accounting/routes.py`,
through a real FastAPI `TestClient` and a real, already-migrated
PostgreSQL database (docs/ROADMAP.md Phase 25 Definition of Done: a real
Command Center consumer of a real accounting condition). Mirrors
`tests/crm/test_routes_integration.py`'s own shape.

This is the test that actually proves the Phase 25 consumer requirement:
not that an event *name* exists, but that a real overdue invoice, posted
through the real service layer, is genuinely returned by the real HTTP
endpoint `frontend/lib/api/accounting.ts::listOverdueInvoices()` calls.
Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.accounting.accounts import create_account
from product.accounting.contacts import tag_contact_role
from product.accounting.invoices import InvoiceLineInput, create_invoice, post_invoice
from product.accounting.periods import create_period
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.crm.contacts import create_contact

from tests.accounting._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_unauthenticated_overdue_invoices_request_is_401() -> None:
    api = TestClient(create_app())
    response = api.get(f"/v1/accounting/tenants/{uuid.uuid4()}/invoices/overdue")
    assert response.status_code == 401


def test_overdue_invoices_route_returns_a_real_overdue_invoice() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable = create_account(
            owner.id, client.tenant_id, code="1100", name="AR", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        create_period(
            owner.id, client.tenant_id, start_date=date(2020, 1, 1), end_date=date(2020, 12, 31)
        )
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Jane", last_name="Customer"
        )
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        overdue = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2020, 1, 1),
            due_date=date(2020, 1, 15),
            lines=[
                InvoiceLineInput(
                    account_id=revenue.id,
                    description="Overdue work",
                    quantity=Decimal("1"),
                    unit_price=Decimal("500.00"),
                )
            ],
        )
        posted = post_invoice(owner.id, client.tenant_id, overdue.id)

        api = TestClient(create_app())
        response = api.get(
            f"/v1/accounting/tenants/{client.tenant_id}/invoices/overdue",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        matching = [row for row in body if row["id"] == str(posted.id)]
        assert len(matching) == 1
        assert matching[0]["invoice_number"] == posted.invoice_number
        assert matching[0]["outstanding_amount"] == "500.00"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_overdue_invoices_route_excludes_not_yet_due_invoice() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        receivable = create_account(
            owner.id, client.tenant_id, code="1100", name="AR", account_type="asset"
        )
        revenue = create_account(
            owner.id, client.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        create_period(
            owner.id, client.tenant_id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Jane", last_name="Customer"
        )
        tag_contact_role(owner.id, client.tenant_id, contact.id, role="customer")
        not_due_yet = create_invoice(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2026, 1, 10),
            due_date=date(2099, 1, 1),
            lines=[
                InvoiceLineInput(
                    account_id=revenue.id,
                    description="Not due yet",
                    quantity=Decimal("1"),
                    unit_price=Decimal("500.00"),
                )
            ],
        )
        posted = post_invoice(owner.id, client.tenant_id, not_due_yet.id)

        api = TestClient(create_app())
        response = api.get(
            f"/v1/accounting/tenants/{client.tenant_id}/invoices/overdue",
            headers=_auth_headers(owner.id),
        )
        assert response.status_code == 200
        body = response.json()
        assert all(row["id"] != str(posted.id) for row in body)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_overdue_invoices_route_is_tenant_isolated() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        receivable = create_account(
            owner.id, client_a.tenant_id, code="1100", name="AR", account_type="asset"
        )
        revenue = create_account(
            owner.id, client_a.tenant_id, code="4000", name="Sales", account_type="revenue"
        )
        create_period(
            owner.id, client_a.tenant_id, start_date=date(2020, 1, 1), end_date=date(2020, 12, 31)
        )
        contact = create_contact(
            owner.id, client_a.tenant_id, first_name="Jane", last_name="Customer"
        )
        tag_contact_role(owner.id, client_a.tenant_id, contact.id, role="customer")
        overdue = create_invoice(
            owner.id,
            client_a.tenant_id,
            contact_id=contact.id,
            receivable_account_id=receivable.id,
            currency="EUR",
            issue_date=date(2020, 1, 1),
            due_date=date(2020, 1, 15),
            lines=[
                InvoiceLineInput(
                    account_id=revenue.id,
                    description="Overdue work",
                    quantity=Decimal("1"),
                    unit_price=Decimal("500.00"),
                )
            ],
        )
        post_invoice(owner.id, client_a.tenant_id, overdue.id)

        api = TestClient(create_app())
        response = api.get(
            f"/v1/accounting/tenants/{client_b.tenant_id}/invoices/overdue",
            headers=_auth_headers(owner.id),
        )
        # `owner` (the same agency owner) also holds an owner role in
        # client_b -- a real, authorized, empty result, never client_a's
        # overdue invoice leaking across the tenant boundary.
        assert response.status_code == 200
        assert response.json() == []
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)
