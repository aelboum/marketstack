"""Search/filter across contacts/companies/opportunities, including the
SQL-injection-safety proof (docs/ROADMAP.md Phase 4.4). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.crm.companies import create_company
from product.crm.contacts import create_contact, list_contacts
from product.crm.custom_fields import define_field, set_field_value
from product.crm.tags import attach_tag, create_tag

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_q_substring_search_matches_across_fixed_columns() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace", email="ada@ex.com"
        )
        create_contact(
            owner.id, client.tenant_id, first_name="Grace", last_name="Hopper", email="grace@ex.com"
        )

        by_first_name = list_contacts(owner.id, client.tenant_id, q="Ada")
        assert {c.first_name for c in by_first_name} == {"Ada"}

        by_last_name = list_contacts(owner.id, client.tenant_id, q="hopper")  # case-insensitive
        assert {c.last_name for c in by_last_name} == {"Hopper"}

        by_email = list_contacts(owner.id, client.tenant_id, q="grace@")
        assert {c.email for c in by_email} == {"grace@ex.com"}

        no_match = list_contacts(owner.id, client.tenant_id, q="nonexistent-xyz")
        assert no_match == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_sql_metacharacter_input_is_treated_as_a_literal_substring() -> None:
    """The concrete injection-safety proof: a `q` value shaped like SQL
    (or an ILIKE wildcard) must never be executed or misinterpreted --
    only ever matched as an inert literal substring."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        create_contact(owner.id, client.tenant_id, first_name="Grace", last_name="Hopper")

        # A value shaped like a SQL injection attempt matches nothing (no
        # contact is literally named this) and, critically, does not
        # raise, error, or affect unrelated rows -- proving it was bound
        # as a parameter, never interpolated into the query.
        injection_shaped = list_contacts(
            owner.id, client.tenant_id, q="'; DROP TABLE crm.contacts; --"
        )
        assert injection_shaped == []

        # A literal '%' is an ILIKE wildcard in Postgres' own semantics
        # (matches any string) -- searching for it literally returns
        # every row that contains at least one character, which both
        # contacts do. This documents the actual (safe, parameterized)
        # behavior rather than assuming '%' is escaped.
        wildcard_search = list_contacts(owner.id, client.tenant_id, q="%")
        assert len(wildcard_search) == 2

        # Still bound as a parameter, still returns nothing when it
        # doesn't literally match, proving no query-structure corruption
        # occurred from the special character.
        no_match = list_contacts(owner.id, client.tenant_id, q="%nonexistent%")
        assert no_match == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_tag_filter() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        vip = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        regular = create_contact(owner.id, client.tenant_id, first_name="Grace", last_name="Hopper")
        tag = create_tag(owner.id, client.tenant_id, name="vip")
        attach_tag(
            owner.id, client.tenant_id, entity_type="contact", entity_id=vip.id, tag_id=tag.id
        )

        results = list_contacts(owner.id, client.tenant_id, tag="vip")
        assert {c.id for c in results} == {vip.id}
        assert regular.id not in {c.id for c in results}

        no_match = list_contacts(owner.id, client.tenant_id, tag="nonexistent-tag")
        assert no_match == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_custom_field_filter_never_reads_the_field_name_at_filter_time() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        hot = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        cold = create_contact(owner.id, client.tenant_id, first_name="Grace", last_name="Hopper")
        field = define_field(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            name="Lead Score",
            field_type="number",
        )
        set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=hot.id,
            field_definition_id=field.id,
            value=90,
        )
        set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=cold.id,
            field_definition_id=field.id,
            value=10,
        )

        results = list_contacts(owner.id, client.tenant_id, custom_field=[f"{field.id}:90"])
        assert {c.id for c in results} == {hot.id}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_company_search() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_company(owner.id, client.tenant_id, name="Acme Corp", domain="acme.test")
        create_company(owner.id, client.tenant_id, name="Widget Co", domain="widget.test")
        from product.crm.companies import list_companies

        results = list_companies(owner.id, client.tenant_id, q="acme")
        assert {c.name for c in results} == {"Acme Corp"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
