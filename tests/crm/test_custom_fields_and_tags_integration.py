"""Custom fields and tags (docs/ROADMAP.md Phase 4.4). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from infra.db import IntegrityError
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import create_contact
from product.crm.custom_fields import (
    define_field,
    get_field_values,
    list_field_definitions,
    set_field_value,
)
from product.crm.errors import CrmAccessDeniedError, CrmValidationError
from product.crm.tags import attach_tag, create_tag, detach_tag, list_tags, list_tags_for_entity

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_define_field_and_set_get_value_round_trip() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        field = define_field(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            name="Lead Score",
            field_type="number",
        )
        assert field.field_type == "number"

        value = set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=contact.id,
            field_definition_id=field.id,
            value=42,
        )
        assert value.value == 42.0

        values = get_field_values(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id
        )
        assert len(values) == 1
        assert values[0].value == 42.0

        # Setting again updates the existing value row, never inserts a
        # second one for the same (definition, entity) pair.
        set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=contact.id,
            field_definition_id=field.id,
            value=99,
        )
        values_after = get_field_values(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id
        )
        assert len(values_after) == 1
        assert values_after[0].value == 99.0

        definitions = list_field_definitions(owner.id, client.tenant_id, "contact")
        assert any(d.id == field.id for d in definitions)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_value_type_mismatch_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        field = define_field(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            name="Lead Score",
            field_type="number",
        )
        with pytest.raises(CrmValidationError):
            set_field_value(
                owner.id,
                client.tenant_id,
                entity_type="contact",
                entity_id=contact.id,
                field_definition_id=field.id,
                value="not-a-number",
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_client_member_without_definition_authority_is_denied() -> None:
    """`CUSTOM_FIELD_DEFINITION_RESOURCE` create is owner-only (member
    role is read-only on it, per `product/crm/event_handlers.py`'s own
    documented reasoning) -- a member cannot define a new field."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    try:
        from core.identity.service import add_tenant_membership
        from core.rbac.scope import RoleScope
        from core.rbac.service import assign_role
        from product.agency.roles import ensure_client_member_role

        role = ensure_client_member_role(client.tenant_id)
        membership = add_tenant_membership(client.tenant_id, member.id)
        assign_role(
            client.tenant_id, membership.id, role.id, scope=RoleScope.SELF, actor_user_id=owner.id
        )

        with pytest.raises(CrmAccessDeniedError):
            define_field(
                member.id, client.tenant_id, entity_type="contact", name="x", field_type="text"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_create_attach_detach_tag_round_trip() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        tag = create_tag(owner.id, client.tenant_id, name="vip")
        assert tag.name == "vip"

        attach_tag(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id, tag_id=tag.id
        )
        tags_for_contact = list_tags_for_entity(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id
        )
        assert [t.id for t in tags_for_contact] == [tag.id]

        detach_tag(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id, tag_id=tag.id
        )
        tags_after = list_tags_for_entity(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id
        )
        assert tags_after == []

        all_tags = list_tags(owner.id, client.tenant_id)
        assert any(t.id == tag.id for t in all_tags)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_attaching_the_same_tag_twice_is_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        tag = create_tag(owner.id, client.tenant_id, name="vip")
        attach_tag(
            owner.id, client.tenant_id, entity_type="contact", entity_id=contact.id, tag_id=tag.id
        )
        with pytest.raises(CrmValidationError):
            attach_tag(
                owner.id,
                client.tenant_id,
                entity_type="contact",
                entity_id=contact.id,
                tag_id=tag.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_custom_field_value_unique_per_entity_enforced_by_database_directly() -> None:
    """Bypasses the service layer's own find-or-update logic to prove the
    `uq_crm_custom_field_values_one_per_entity` constraint itself rejects
    a duplicate row -- the service layer's own upsert behavior is a
    convenience, the constraint is the real guarantee."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace")
        field = define_field(
            owner.id, client.tenant_id, entity_type="contact", name="Score", field_type="number"
        )
        from infra.db import tenant_session_scope
        from product.crm.models import CustomFieldValue

        with tenant_session_scope(client.tenant_id) as session:
            session.add(
                CustomFieldValue(
                    tenant_id=client.tenant_id,
                    field_definition_id=field.id,
                    contact_id=contact.id,
                    value_number=1,
                )
            )
            session.flush()

        # The second insert's IntegrityError must propagate all the way out
        # of the `with tenant_session_scope(...)` block itself (not be
        # caught and swallowed inside it) -- tenant_session_scope()'s own
        # context manager rolls back on an exception exiting its body;
        # catching the error *inside* the block and letting the block then
        # try to commit a dead transaction raises a second, unrelated
        # PendingRollbackError instead of the real one.
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client.tenant_id) as session:
                session.add(
                    CustomFieldValue(
                        tenant_id=client.tenant_id,
                        field_definition_id=field.id,
                        contact_id=contact.id,
                        value_number=2,
                    )
                )
                session.flush()
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
