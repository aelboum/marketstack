"""Contact CRUD (docs/ROADMAP.md Phase 4.1).

`phone`, if supplied, is normalized via `product.foundation.values
.normalize_phone_number()` before storage -- the stored form is always
E.164 or absent, never an unnormalized caller-supplied string.
`InvalidPhoneNumberError` (from `product.foundation.values`) propagates
unchanged on a malformed number -- a 400-shaped client input error, not
an authorization/lookup failure, mapped at `product/crm/routes.py`.

`company_id`, if supplied, is validated against `tenant_id` explicitly
before the insert/update (`CrmReferenceNotFoundError` on a mismatch or
unknown id) -- defense in depth on top of, never instead of, the
composite-FK constraint on `crm.contacts.company_id` itself
(`product/crm/models.py`), which is what actually makes a cross-tenant
reference impossible at the database level.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError
from product.crm.models import ENTITY_TYPE_CONTACT, Company, Contact
from product.crm.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.crm.permissions import CONTACT_RESOURCE, require
from product.crm.search import apply_custom_field_filters, apply_tag_filter, apply_text_search
from product.foundation.values import normalize_phone_number


@dataclass(frozen=True, slots=True)
class ContactView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    company_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: Contact) -> ContactView:
    return ContactView(
        id=row.id,
        tenant_id=row.tenant_id,
        first_name=row.first_name,
        last_name=row.last_name,
        email=row.email,
        phone=row.phone,
        company_id=row.company_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalized_phone(phone: str | None) -> str | None:
    return None if phone is None else str(normalize_phone_number(phone))


def _require_company_in_tenant(session, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
    company = session.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise CrmReferenceNotFoundError("company", company_id)


def create_contact(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    company_id: uuid.UUID | None = None,
) -> ContactView:
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="create")
    normalized_phone = _normalized_phone(phone)
    with tenant_session_scope(tenant_id) as session:
        if company_id is not None:
            _require_company_in_tenant(session, tenant_id, company_id)
        row = Contact(
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=normalized_phone,
            company_id=company_id,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.contact.create",
        resource_type="crm.contact",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_contact(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> ContactView:
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Contact, contact_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("contact", contact_id)
        session.expunge(row)
    return _to_view(row)


def list_contacts(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] | None = None,
) -> list[ContactView]:
    """`q` substring-matches (parameterized ILIKE) across `first_name`/
    `last_name`/`email`/`phone`. `tag` exact-matches an attached tag's
    name. `custom_field` is zero or more `"<definition_id>:<value>"`
    filters -- see `product/crm/search.py`'s own module docstring for the
    injection-safety discipline every one of these follows."""
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        stmt = select(Contact).where(Contact.tenant_id == tenant_id)
        stmt = apply_text_search(
            stmt, Contact, (Contact.first_name, Contact.last_name, Contact.email, Contact.phone), q
        )
        stmt = apply_tag_filter(stmt, Contact, ENTITY_TYPE_CONTACT, tenant_id, tag)
        stmt = apply_custom_field_filters(
            stmt,
            Contact,
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE_CONTACT,
            custom_field_params=custom_field,
            session=session,
        )
        rows = (
            session.execute(
                stmt.order_by(Contact.created_at.desc()).limit(bounded_limit).offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_contact(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    company_id: uuid.UUID | None = None,
    _clear_company: bool = False,
) -> ContactView:
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="update")
    normalized_phone = _normalized_phone(phone) if phone is not None else None
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Contact, contact_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("contact", contact_id)
        if first_name is not None:
            row.first_name = first_name
        if last_name is not None:
            row.last_name = last_name
        if email is not None:
            row.email = email
        if phone is not None:
            row.phone = normalized_phone
        if company_id is not None:
            _require_company_in_tenant(session, tenant_id, company_id)
            row.company_id = company_id
        elif _clear_company:
            row.company_id = None
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.contact.update",
        resource_type="crm.contact",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_contact(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Contact, contact_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("contact", contact_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.contact.delete",
        resource_type="crm.contact",
        resource_id=str(contact_id),
        outcome=AuditOutcome.SUCCESS,
    )
