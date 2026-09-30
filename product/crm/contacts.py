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

`create_contact()` publishes `crm.contact.created` (docs/ROADMAP.md
Phase 10.2's own trigger library) -- added as a single, additive
`publish()` call, mirroring `product/crm/opportunities.py
::change_stage()`'s own `crm.opportunity.stage_changed` precedent
exactly; no other behavior in this module changed for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import acquire_tenant_advisory_lock, select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError
from product.crm.models import ENTITY_TYPE_CONTACT, Company, Contact
from product.crm.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.crm.permissions import CONTACT_RESOURCE, require
from product.crm.search import apply_custom_field_filters, apply_tag_filter, apply_text_search
from product.foundation.events import Event, publish
from product.foundation.values import normalize_phone_number

CONTACT_CREATED_EVENT_TYPE = "crm.contact.created"
CONTACT_CREATED_EVENT_VERSION = 1


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
    publish(
        Event(
            type=CONTACT_CREATED_EVENT_TYPE,
            version=CONTACT_CREATED_EVENT_VERSION,
            tenant_id=str(tenant_id),
            payload={"contact_id": str(row.id)},
        )
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


def create_or_update_contact_from_trusted_source(
    tenant_id: uuid.UUID,
    *,
    email: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    source: str,
) -> ContactView:
    """Find-or-create a contact by exact `email` match within `tenant_id`,
    with **no `actor_user_id` parameter and no `product.crm.permissions
    .require()` call** -- deliberately, mirroring the exact "trusts its
    caller" precedent category `saas-os` itself already establishes
    repeatedly (`core.tenancy.create_tenant()`, `core.identity
    .add_tenant_membership()`, `core.rbac.create_support_access_request()`
    -- each ungated because there is no pre-existing authority to check
    yet, each narrowly named/documented so no ordinary caller reaches for
    it by accident).

    Reserved exclusively for the small, closed set of public,
    unauthenticated capture paths this product deliberately grants an edge
    to CRM for (`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`,
    `docs/ADR/0015-websites-depends-on-crm.md`): `product/marketing/forms.py
    ::submit_form()` (docs/ROADMAP.md Phase 6.3), `product/appointments
    /booking.py::book_appointment()`'s public path (Phase 7.2), and
    `product/websites/leads.py::capture_lead()` (Phase 22) -- each a
    legitimately anonymous write path, never a fourth without its own ADR.
    Never call this from any authenticated route or service function that
    already has a real `actor_user_id` available; use `create_contact()`/
    `update_contact()` there instead, which correctly enforce
    authorization. This function is never exposed directly over HTTP by
    `product/crm/routes.py` itself.

    `source` is a short, bounded, non-PII string recorded only via
    `core.audit_log` metadata (e.g. `"form:<form_id>"`) so a contact's
    origin is traceable without itself being personal data.

    An existing contact's `first_name`/`last_name`/`phone` are updated
    only when the incoming value is non-empty -- a blank field on a
    resubmitted form must never blank out data already on file.
    `company_id` is never touched here (forms do not collect a company;
    out of scope for this function).

    `email` has no unique constraint/index on `crm.contacts` today (see
    migration `0019_add_crm_contacts_email_index` -- an index was added
    specifically because this function's lookup-by-email is now a real,
    repeated query path, not just an occasional one; there is still no
    uniqueness constraint on `email` itself, since a tenant may
    legitimately hold more than one contact sharing an email address
    (e.g. shared household/team inboxes) -- this function updates the
    *first* match by `created_at`, deterministically, rather than
    picking arbitrarily among duplicates)."""
    with tenant_session_scope(tenant_id) as session:
        existing = (
            session.execute(
                select(Contact)
                .where(Contact.tenant_id == tenant_id, Contact.email == email)
                .order_by(Contact.created_at.asc())
                .limit(1)
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            if first_name:
                existing.first_name = first_name
            if last_name:
                existing.last_name = last_name
            if phone:
                existing.phone = _normalized_phone(phone)
            session.flush()
            session.refresh(existing)
            session.expunge(existing)
            row = existing
            action = "crm.contact.update_from_trusted_source"
        else:
            row = Contact(
                tenant_id=tenant_id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=_normalized_phone(phone),
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            action = "crm.contact.create_from_trusted_source"
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action=action,
        resource_type="crm.contact",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"source": source},
    )
    return _to_view(row)


def create_or_reuse_contact_from_trusted_source_by_phone(
    tenant_id: uuid.UUID,
    *,
    phone: str,
    source: str,
    first_name: str = "Unverified",
    last_name: str = "Contact",
) -> ContactView:
    """Phase 30 (docs/ROADMAP.md "Unified Inbox"), authorized by
    `docs/ADR/0019-conversations-depends-on-crm.md` and, for the trust
    contract it must follow, `docs/ADR/0018
    -inbound-phone-caller-contact-trust-boundary.md` point 8. The one
    published entry point `product.conversations` is granted into
    `product.crm` for phone-keyed inbound correlation -- never call this
    from any other module.

    **Deliberately a *different* contract from
    `create_or_update_contact_from_trusted_source()` above, not a phone
    overload of it.** That function updates a matched contact's
    `first_name`/`last_name`/`phone` from the caller-supplied values.
    ADR-0018 point 8 is explicit that phone-based correlation must
    "never mutate or upgrade trusted information" on a match -- so this
    function only ever *creates* a new contact or *reuses* an existing one
    unchanged; it never writes to an existing row. Same "no `actor_user_id`
    parameter, no `product.crm.permissions.require()` call" trusted-caller
    shape as its sibling, for the identical reason (there is no
    authenticated actor on this path -- the caller is an unauthenticated
    inbound phone identifier, per ADR-0018).

    **Lookup key is `(tenant_id, normalized phone)`, never phone alone** --
    `phone` is normalized via the same `product.foundation.values
    .normalize_phone_number()` every other phone-bearing column in this
    product uses (no second normalization algorithm). A match in one
    tenant is never returned for another tenant; `crm.contacts` has no
    global phone index, only this function's own tenant-scoped query.

    **Correlation is not authentication** (ADR-0018 point 8, restated here
    because this is the one function that could be mistaken for granting
    it): a returned match means only "an inbound message from this same
    normalized phone number, in this same tenant, has been associated with
    a contact record before." It is never treated, logged, or documented
    as proof that the current sender is the person that record represents,
    and reusing it grants no authorization of any kind.

    **New contacts remain explicitly unverified.** `first_name`/`last_name`
    default to a visible placeholder (never blank, since the column is
    `NOT NULL`) precisely so a phone-originated contact record is never
    indistinguishable from a verified or staff-entered one at a glance; a
    human can rename it later through the ordinary authenticated
    `update_contact()` once/if a real identity is established -- that
    later step is outside this function's own contract. `source` is the
    same short, bounded, non-PII provenance string
    `create_or_update_contact_from_trusted_source()` already records
    (e.g. `"sms:unverified"`/`"whatsapp:unverified"`), audited via
    `core.audit_log` metadata only -- no new "verified" column or schema
    change is introduced; provenance lives entirely in the audit trail,
    mirroring that function's own discipline exactly.

    **Concurrency**: `crm.contacts` carries no unique constraint on phone
    (ADR-0018's own disposition table notes this explicitly -- "`contacts
    .phone` has no uniqueness constraint"), so a bare
    select-then-insert here would race under concurrent duplicate inbound
    delivery. Serialized instead with `infra.db
    .acquire_tenant_advisory_lock()` (`pg_advisory_xact_lock`, the same
    primitive `product/accounting/invoices.py::post_invoice()`'s own
    gapless-numbering allocation already uses for the identical
    "no unique constraint backs this lookup" shape), keyed on
    `(tenant_id, normalized phone)`, held for this function's own
    transaction only. A second, concurrent caller blocks until the first
    commits, then re-reads and finds the row the first caller just
    created -- both calls return the same contact, never two."""
    normalized = normalize_phone_number(phone)
    with tenant_session_scope(tenant_id) as session:
        acquire_tenant_advisory_lock(
            session, tenant_id, f"crm.contact_by_phone.{tenant_id}.{normalized.e164}"
        )
        existing = (
            session.execute(
                select(Contact)
                .where(Contact.tenant_id == tenant_id, Contact.phone == normalized.e164)
                .order_by(Contact.created_at.asc())
                .limit(1)
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            session.expunge(existing)
            row = existing
            action = "crm.contact.reuse_from_trusted_source_by_phone"
        else:
            row = Contact(
                tenant_id=tenant_id,
                first_name=first_name,
                last_name=last_name,
                phone=normalized.e164,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            action = "crm.contact.create_from_trusted_source_by_phone"
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.SYSTEM,
        action=action,
        resource_type="crm.contact",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"source": source},
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
