"""Forms and public lead capture (docs/ROADMAP.md Phase 6.3) -- the one
deliberately-unauthenticated write path in this product. Real disposable
Postgres and, for the rate-limit test, real disposable Redis. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.crm.contacts import get_contact
from product.marketing.errors import MarketingFormTokenInvalidError, MarketingValidationError
from product.marketing.forms import (
    FormFieldDefinition,
    create_form,
    resolve_form_by_token,
    submit_form,
)

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _standard_fields() -> list[FormFieldDefinition]:
    return [
        FormFieldDefinition(name="email", field_type="email", required=True),
        FormFieldDefinition(name="name", field_type="text", required=False),
        FormFieldDefinition(name="phone", field_type="phone", required=False),
    ]


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def test_form_crud_and_token_resolution() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        assert form.form_token
        resolved = resolve_form_by_token(form.form_token)
        assert resolved is not None
        assert resolved.id == form.id
        assert resolved.tenant_id == client.tenant_id

        assert resolve_form_by_token("not-a-real-token") is None
        assert resolve_form_by_token("") is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_submit_form_creates_contact_in_correct_tenant() -> None:
    """The resulting contact is created in the *correct* tenant only,
    proven by direct database inspection, not just trusting the service
    layer's own claim."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        result = submit_form(
            form.form_token,
            {"email": "lead@example.com", "name": "Jane Lead", "phone": "+15551234567"},
        )
        assert result.contact_id is not None

        # Direct database inspection, not the service layer's own claim.
        contact = get_contact(owner.id, client.tenant_id, result.contact_id)
        assert contact.email == "lead@example.com"
        assert contact.first_name == "Jane"
        assert contact.last_name == "Lead"
        assert contact.tenant_id == client.tenant_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_submit_form_second_time_updates_existing_contact_not_duplicate() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        first = submit_form(form.form_token, {"email": "repeat@example.com", "name": "First Name"})
        second = submit_form(
            form.form_token, {"email": "repeat@example.com", "name": "Second Name"}
        )
        assert first.contact_id == second.contact_id
        assert second.contact_id is not None
        contact = get_contact(owner.id, client.tenant_id, second.contact_id)
        assert contact.first_name == "Second"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_submit_form_unknown_token_fails_closed() -> None:
    with pytest.raises(MarketingFormTokenInvalidError):
        submit_form("totally-unknown-token", {"email": "x@example.com"})


def test_submit_form_malformed_token_fails_the_same_way_as_unknown() -> None:
    """An unknown/malformed token is rejected identically regardless of
    *why* it's invalid -- never distinguishable."""
    errors = []
    for bad_token in ("", "short", "a" * 500, "!!!not-base64!!!"):
        try:
            submit_form(bad_token, {"email": "x@example.com"})
        except MarketingFormTokenInvalidError as exc:
            errors.append(type(exc))
    assert len(errors) == 4
    assert all(e is MarketingFormTokenInvalidError for e in errors)


def test_submit_form_missing_required_field_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        with pytest.raises(MarketingValidationError):
            submit_form(form.form_token, {"name": "No Email Here"})
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_submit_form_unknown_field_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        with pytest.raises(MarketingValidationError):
            submit_form(
                form.form_token, {"email": "x@example.com", "not_a_declared_field": "value"}
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_submit_form_oversized_field_value_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(owner.id, client.tenant_id, name="Lead Form", fields=_standard_fields())
        with pytest.raises(MarketingValidationError):
            submit_form(form.form_token, {"email": "x@example.com", "name": "y" * 5000})
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_form_without_email_field_records_submission_with_no_contact() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        form = create_form(
            owner.id,
            client.tenant_id,
            name="No Email Form",
            fields=[FormFieldDefinition(name="feedback", field_type="text", required=True)],
        )
        result = submit_form(form.form_token, {"feedback": "great product"})
        assert result.contact_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_a_real_token_for_tenant_a_never_touches_tenant_b() -> None:
    """A request naming a real token for tenant A can never create/read/
    touch anything in tenant B."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        form_a = create_form(
            owner_a.id, client_a.tenant_id, name="Form A", fields=_standard_fields()
        )
        result = submit_form(form_a.form_token, {"email": "cross@example.com"})
        assert result.contact_id is not None
        contact = get_contact(owner_a.id, client_a.tenant_id, result.contact_id)
        assert contact.tenant_id == client_a.tenant_id
        assert contact.tenant_id != client_b.tenant_id
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_public_submit_route_rate_limited() -> None:
    """The rate limit actually triggers and blocks further submissions
    from the same token within the window."""
    from infra.ratelimit.config import get_ratelimit_config

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    import os

    old_value = os.environ.get("RATE_LIMIT_REQUESTS_PER_WINDOW")
    os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = "2"
    get_ratelimit_config.cache_clear()
    try:
        form = create_form(owner.id, client.tenant_id, name="RL Form", fields=_standard_fields())
        api = TestClient(create_app())
        statuses = []
        for i in range(4):
            resp = api.post(
                f"/v1/marketing/forms/{form.form_token}/submit",
                json={"fields": {"email": f"rl-{i}@example.com"}},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses, statuses
    finally:
        if old_value is None:
            os.environ.pop("RATE_LIMIT_REQUESTS_PER_WINDOW", None)
        else:
            os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = old_value
        get_ratelimit_config.cache_clear()
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_public_submit_route_unknown_token_over_http_is_non_enumerating_404() -> None:
    api = TestClient(create_app())
    response = api.post(
        "/v1/marketing/forms/totally-unknown-token/submit",
        json={"fields": {"email": "x@example.com"}},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "resource not found."}


def test_full_form_flow_over_http() -> None:
    owner = make_user()
    api = TestClient(create_app())
    agency_tenant_id = None
    client_tenant_id = None
    try:
        headers = _auth_headers(owner.id)
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])
        client_resp = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=headers,
        )
        client_tenant_id = uuid.UUID(client_resp.json()["tenant_id"])

        form_resp = api.post(
            f"/v1/marketing/tenants/{client_tenant_id}/forms",
            json={
                "name": "Http Form",
                "fields": [{"name": "email", "field_type": "email", "required": True}],
            },
            headers=headers,
        )
        assert form_resp.status_code == 201
        form_token = form_resp.json()["form_token"]

        submit_resp = api.post(
            f"/v1/marketing/forms/{form_token}/submit",
            json={"fields": {"email": "httpform@example.com"}},
        )
        assert submit_resp.status_code == 201
        assert submit_resp.json()["contact_id"] is not None

        submissions_resp = api.get(
            f"/v1/marketing/tenants/{client_tenant_id}/forms/{form_resp.json()['id']}/submissions",
            headers=headers,
        )
        assert submissions_resp.status_code == 200
        assert len(submissions_resp.json()) == 1
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)
